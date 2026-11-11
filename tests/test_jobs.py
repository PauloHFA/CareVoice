from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from carevoice.db.database import Database
from carevoice.db.models import AuditLog, Patient, ProcessingJob
from carevoice.domain.identity import ConsentRequired, IdentityService
from carevoice.jobs.queue import InvalidJobTransition, JobQueue
from carevoice.security.crypto import FieldCipher

ADMIN_CHAT_ID = "admin-chat"


@pytest.fixture
def job_context() -> Generator[tuple[IdentityService, JobQueue, Database], None, None]:
    database = Database("sqlite:///:memory:")
    database.create_schema_for_tests()
    cipher = FieldCipher(Fernet.generate_key().decode("ascii"))
    identity = IdentityService(database.sessions, cipher, ADMIN_CHAT_ID)
    invitation = identity.create_invitation(
        ADMIN_CHAT_ID,
        name="Terapeuta",
        profession="Fonoaudióloga",
        council_registry="REG-123",
    )
    identity.consume_invitation(invitation, "chat-one")
    patient = identity.create_patient("chat-one", display_name="Paciente de Teste")
    identity.grant_consent(
        "chat-one",
        patient.id,
        terms_version="v1",
        purpose="processamento local",
    )
    queue = JobQueue(database.sessions, identity, cipher, base_retry_seconds=1)
    yield identity, queue, database
    database.dispose()


def test_audio_job_is_encrypted_claimed_and_completed(
    job_context: tuple[IdentityService, JobQueue, Database],
) -> None:
    _, queue, database = job_context
    payload = b"fictitious audio payload"
    job_id = queue.enqueue_audio(
        "chat-one",
        _patient_id(database),
        filename="recording.ogg",
        payload=payload,
        duration_seconds=20,
        content_type="audio/ogg",
    )

    with database.sessions() as session:
        job = session.get(ProcessingJob, job_id)
        assert job is not None
        assert payload not in job.payload_enc

    claimed = queue.claim_next()
    assert claimed is not None
    assert claimed.id == job_id
    assert claimed.kind == "audio"
    assert claimed.payload == payload
    assert claimed.attempts == 1

    queue.assert_claim_is_authorized(job_id)
    queue.complete(job_id)
    with pytest.raises(InvalidJobTransition):
        queue.complete(job_id)


def test_text_job_requires_minimum_content_and_current_consent(
    job_context: tuple[IdentityService, JobQueue, Database],
) -> None:
    identity, queue, database = job_context
    patient_id = _patient_id(database)
    with pytest.raises(ValueError, match="more than 30 characters"):
        queue.enqueue_text("chat-one", patient_id, "too short")

    queue.enqueue_text("chat-one", patient_id, "A" * 31)
    identity.revoke_consent("chat-one", patient_id)

    assert queue.claim_next() is None
    with database.sessions() as session:
        job = session.scalar(select(ProcessingJob))
        assert job is not None
        assert job.status == "failed"
        assert job.error_code == "consent_revoked"


def test_revoking_consent_after_claim_prevents_processing_and_commits_failure(
    job_context: tuple[IdentityService, JobQueue, Database],
) -> None:
    identity, queue, database = job_context
    patient_id = _patient_id(database)
    job_id = queue.enqueue_text("chat-one", patient_id, "A" * 40)
    assert queue.claim_next() is not None
    identity.revoke_consent("chat-one", patient_id)

    with pytest.raises(ConsentRequired):
        queue.assert_claim_is_authorized(job_id)

    with database.sessions() as session:
        job = session.get(ProcessingJob, job_id)
        assert job is not None
        assert job.status == "failed"
        assert job.error_code == "consent_revoked"


def test_retry_uses_backoff_and_stops_at_attempt_limit(
    job_context: tuple[IdentityService, JobQueue, Database],
) -> None:
    _, queue, database = job_context
    patient_id = _patient_id(database)
    job_id = queue.enqueue_text("chat-one", patient_id, "A" * 40)
    first_claim = queue.claim_next()
    assert first_claim is not None
    assert queue.fail(job_id, "provider_unavailable") is True
    assert queue.claim_next() is None

    with database.sessions.begin() as session:
        job = session.get(ProcessingJob, job_id)
        assert job is not None
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)

    second_claim = queue.claim_next()
    assert second_claim is not None
    assert second_claim.attempts == 2
    assert queue.fail(job_id, "invalid_payload") is False

    with database.sessions() as session:
        job = session.get(ProcessingJob, job_id)
        assert job is not None
        assert job.status == "failed"
        assert job.error_code == "invalid_payload"


def test_audit_for_jobs_does_not_store_payload(
    job_context: tuple[IdentityService, JobQueue, Database],
) -> None:
    _, queue, database = job_context
    patient_id = _patient_id(database)
    queue.enqueue_text("chat-one", patient_id, "clinical text should never enter the audit")

    with database.sessions() as session:
        events = session.scalars(select(AuditLog)).all()
        audit_content = " ".join(
            f"{event.action} {event.object_type} {event.object_id}" for event in events
        )

    assert "job.enqueued" in audit_content
    assert "clinical text should never enter the audit" not in audit_content


def _patient_id(database: Database) -> str:
    with database.sessions() as session:
        patient = session.scalar(select(Patient))
        assert patient is not None
        return patient.id
