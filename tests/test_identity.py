from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from carevoice.db.database import Database
from carevoice.db.models import AuditLog, Consent, Guardian, Invitation, Patient, Professional
from carevoice.domain.identity import (
    AuthenticationError,
    AuthorizationError,
    ConsentRequired,
    IdentityService,
    InvitationError,
    ResourceNotFound,
)
from carevoice.security.crypto import FieldCipher

ADMIN_CHAT_ID = "admin-chat"


@pytest.fixture
def identity() -> Generator[tuple[IdentityService, Database], None, None]:
    database = Database("sqlite:///:memory:")
    database.create_schema_for_tests()
    service = IdentityService(
        database.sessions,
        FieldCipher(Fernet.generate_key().decode("ascii")),
        ADMIN_CHAT_ID,
    )
    yield service, database
    database.dispose()


def register_professional(
    service: IdentityService,
    chat_id: str,
    *,
    name: str = "Profissional Exemplo",
) -> str:
    invitation = service.create_invitation(
        ADMIN_CHAT_ID,
        name=name,
        profession="Terapeuta ocupacional",
        council_registry="REG-123",
    )
    return service.consume_invitation(invitation, chat_id)


def test_invitation_links_once_and_requires_admin(
    identity: tuple[IdentityService, Database],
) -> None:
    service, _ = identity
    with pytest.raises(AuthorizationError):
        service.create_invitation(
            "not-admin",
            name="Pessoa",
            profession="Terapeuta",
            council_registry="REG-1",
        )

    invitation = service.create_invitation(
        ADMIN_CHAT_ID,
        name="Pessoa",
        profession="Terapeuta",
        council_registry="REG-1",
    )
    professional_id = service.consume_invitation(invitation, "chat-one")

    assert professional_id
    with pytest.raises(InvitationError, match="already used"):
        service.consume_invitation(invitation, "chat-two")
    with pytest.raises(InvitationError, match="invalid or already used"):
        service.consume_invitation("invalid-code", "chat-three")


def test_invitation_setup_rejects_missing_admin_and_nonpositive_lifetime(
    identity: tuple[IdentityService, Database],
) -> None:
    service, database = identity
    with pytest.raises(ValueError, match="administrator chat identity"):
        IdentityService(
            database.sessions,
            FieldCipher(Fernet.generate_key().decode("ascii")),
            "",
        )
    with pytest.raises(ValueError, match="lifetime must be positive"):
        service.create_invitation(
            ADMIN_CHAT_ID,
            name="Pessoa",
            profession="Terapeuta",
            council_registry="REG-1",
            expires_in=timedelta(0),
        )


def test_invitation_expiry_and_duplicate_chat_are_rejected(
    identity: tuple[IdentityService, Database],
) -> None:
    service, _ = identity
    expired = service.create_invitation(
        ADMIN_CHAT_ID,
        name="Pessoa",
        profession="Terapeuta",
        council_registry="REG-1",
        expires_in=timedelta(hours=1),
    )
    _, database = identity
    with database.sessions.begin() as session:
        invitation_row = session.scalar(select(Invitation))
        assert invitation_row is not None
        invitation_row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(InvitationError, match="expired"):
        service.consume_invitation(expired, "chat-expired")

    other_invitation = service.create_invitation(
        ADMIN_CHAT_ID,
        name="Outra pessoa",
        profession="Terapeuta",
        council_registry="REG-2",
    )
    register_professional(service, "already-linked")
    with pytest.raises(InvitationError, match="already linked"):
        service.consume_invitation(other_invitation, "already-linked")


def test_professional_revocation_removes_access_immediately(
    identity: tuple[IdentityService, Database],
) -> None:
    service, _ = identity
    professional_id = register_professional(service, "chat-one")

    service.revoke_professional(ADMIN_CHAT_ID, professional_id)

    with pytest.raises(AuthenticationError):
        service.list_patients("chat-one")


def test_patient_data_is_encrypted_and_scoped_to_owner(
    identity: tuple[IdentityService, Database],
) -> None:
    service, database = identity
    register_professional(service, "chat-one")
    register_professional(service, "chat-two", name="Outra profissional")

    patient = service.create_patient(
        "chat-one",
        display_name="Paciente de Teste",
        alias="P-01",
        birth_date=date(2018, 4, 2),
        guardian_name="Responsável de Teste",
        guardian_relationship="Responsável",
        guardian_contact="contato-ficticio",
    )

    assert service.list_patients("chat-one")[0].display_name == "Paciente de Teste"
    assert service.list_patients("chat-two") == []
    with pytest.raises(ResourceNotFound):
        service.grant_consent(
            "chat-two",
            patient.id,
            terms_version="1",
            purpose="teste fictício",
        )

    with database.sessions() as session:
        patient_row = session.get(Patient, patient.id)
        guardian_row = session.scalar(select(Guardian).where(Guardian.patient_id == patient.id))
        assert patient_row is not None
        assert guardian_row is not None
        assert "Paciente de Teste" not in patient_row.display_name_enc
        assert "contato-ficticio" not in guardian_row.contact_enc
        professional_rows = session.scalars(select(Professional)).all()
        assert all("chat-one" not in row.chat_id_digest for row in professional_rows)


def test_consent_is_required_and_revocation_blocks_processing(
    identity: tuple[IdentityService, Database],
) -> None:
    service, database = identity
    register_professional(service, "chat-one")
    patient = service.create_patient("chat-one", display_name="Paciente")

    with pytest.raises(ConsentRequired):
        service.require_processing_consent("chat-one", patient.id)

    service.grant_consent(
        "chat-one",
        patient.id,
        terms_version="v1",
        purpose="processamento para gerar rascunho",
        evidence_ref="evidencia-ficticia",
    )
    service.grant_consent(
        "chat-one",
        patient.id,
        terms_version="v2",
        purpose="renovação do consentimento",
    )
    service.require_processing_consent("chat-one", patient.id)
    service.revoke_consent("chat-one", patient.id)

    with pytest.raises(ConsentRequired):
        service.require_processing_consent("chat-one", patient.id)

    with database.sessions() as session:
        consent = session.scalar(select(Consent).where(Consent.patient_id == patient.id))
        assert consent is not None
        assert "processamento" not in consent.purpose_enc
        assert "ficticia" not in consent.evidence_ref_enc


def test_goals_are_owned_and_returned_in_plaintext_only_to_the_owner(
    identity: tuple[IdentityService, Database],
) -> None:
    service, _ = identity
    register_professional(service, "chat-one")
    register_professional(service, "chat-two")
    patient = service.create_patient("chat-one", display_name="Paciente")

    goal = service.create_goal(
        "chat-one",
        patient.id,
        description="Parear cores",
        area="cognição",
        indicator_type="percentage",
        mastery_criterion="80% de acerto",
    )

    assert service.list_goals("chat-one", patient.id) == [goal]
    with pytest.raises(ResourceNotFound):
        service.list_goals("chat-two", patient.id)


def test_audit_records_metadata_without_patient_content(
    identity: tuple[IdentityService, Database],
) -> None:
    service, database = identity
    register_professional(service, "chat-one")
    service.create_patient("chat-one", display_name="Nome Clínico Fictício")

    with database.sessions() as session:
        audit_text = " ".join(
            f"{row.action} {row.object_type} {row.object_id}"
            for row in session.scalars(select(AuditLog)).all()
        )

    assert "patient.created" in audit_text
    assert "Nome Clínico Fictício" not in audit_text
