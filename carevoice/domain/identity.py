"""Professional access, patient records, consent, goals, and scoped audit."""

import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from carevoice.db.models import (
    AuditLog,
    Consent,
    Goal,
    Guardian,
    Invitation,
    Patient,
    Professional,
    new_id,
    utc_now,
)
from carevoice.security.crypto import FieldCipher

IndicatorType = Literal["percentage", "duration", "count", "scale"]
PatientTemplate = Literal["SOAP", "ABC", "FREE"]


class AuthenticationError(Exception):
    """Raised when a professional or administrator cannot be authenticated."""


class AuthorizationError(Exception):
    """Raised when an authenticated actor lacks permission."""


class ResourceNotFound(Exception):
    """Raised when a resource is absent or not owned by the requesting professional."""


class InvitationError(Exception):
    """Raised when an invitation is invalid, expired, used, or cannot be linked."""


class ConsentRequired(Exception):
    """Raised when processing is attempted without current consent."""


@dataclass(frozen=True)
class PatientRecord:
    id: str
    display_name: str
    alias: str | None
    birth_date: str | None
    template: str
    active: bool


@dataclass(frozen=True)
class GoalRecord:
    id: str
    description: str
    area: str
    indicator_type: IndicatorType
    mastery_criterion: str
    status: str


class IdentityService:
    """Identity and patient operations with explicit owner scoping."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        cipher: FieldCipher,
        administrator_chat_id: str,
    ) -> None:
        if not administrator_chat_id:
            raise ValueError("An administrator chat identity is required")
        self._sessions = sessions
        self._cipher = cipher
        self._administrator_digest = cipher.digest(administrator_chat_id)

    def _require_admin(self, chat_id: str) -> None:
        if not hmac.compare_digest(self._cipher.digest(chat_id), self._administrator_digest):
            raise AuthorizationError("Administrator permission required")

    def _require_professional(self, session: Session, chat_id: str) -> Professional:
        professional = session.scalar(
            select(Professional).where(
                Professional.chat_id_digest == self._cipher.digest(chat_id),
                Professional.active.is_(True),
            )
        )
        if professional is None:
            raise AuthenticationError("Professional access is not active")
        return professional

    @staticmethod
    def _audit(
        session: Session,
        actor_id: str,
        action: str,
        object_type: str,
        object_id: str,
    ) -> None:
        session.add(
            AuditLog(
                id=new_id(),
                actor_id=actor_id,
                action=action,
                object_type=object_type,
                object_id=object_id,
            )
        )

    def create_invitation(
        self,
        administrator_chat_id: str,
        *,
        name: str,
        profession: str,
        council_registry: str,
        specialty: str | None = None,
        timezone: str = "America/Fortaleza",
        expires_in: timedelta = timedelta(hours=24),
    ) -> str:
        self._require_admin(administrator_chat_id)
        if expires_in <= timedelta(0):
            raise ValueError("Invitation lifetime must be positive")

        code = secrets.token_urlsafe(32)
        professional_id = new_id()
        with self._sessions.begin() as session:
            professional = Professional(
                id=professional_id,
                name_enc=self._cipher.encrypt(name),
                profession_enc=self._cipher.encrypt(profession),
                council_registry_enc=self._cipher.encrypt(council_registry),
                specialty_enc=self._cipher.encrypt(specialty),
                timezone=timezone,
                active=True,
            )
            session.add(professional)
            session.flush()
            session.add(
                Invitation(
                    id=new_id(),
                    professional_id=professional_id,
                    code_digest=self._cipher.digest(code),
                    expires_at=utc_now() + expires_in,
                )
            )
            self._audit(
                session,
                "administrator",
                "invitation.created",
                "professional",
                professional_id,
            )
        return code

    def consume_invitation(self, code: str, chat_id: str) -> str:
        code_digest = self._cipher.digest(code)
        chat_digest = self._cipher.digest(chat_id)
        professional_id = ""
        try:
            with self._sessions.begin() as session:
                invitation = session.scalar(
                    select(Invitation)
                    .where(Invitation.code_digest == code_digest)
                    .with_for_update()
                )
                if invitation is None or invitation.consumed_at is not None:
                    raise InvitationError("Invitation is invalid or already used")
                if _as_utc(invitation.expires_at) <= utc_now():
                    raise InvitationError("Invitation has expired")
                professional = session.get(Professional, invitation.professional_id)
                if professional is None or not professional.active or professional.chat_id_digest:
                    raise InvitationError("Invitation cannot be linked")
                if session.scalar(
                    select(Professional.id).where(Professional.chat_id_digest == chat_digest)
                ):
                    raise InvitationError("This chat is already linked")
                result = session.execute(
                    update(Invitation)
                    .where(Invitation.id == invitation.id, Invitation.consumed_at.is_(None))
                    .values(consumed_at=utc_now())
                    .returning(Invitation.id)
                )
                if result.scalar_one_or_none() is None:
                    raise InvitationError("Invitation is invalid or already used")
                professional.chat_id_digest = chat_digest
                professional_id = professional.id
                self._audit(
                    session,
                    professional_id,
                    "professional.linked",
                    "professional",
                    professional_id,
                )
        except IntegrityError as exc:
            raise InvitationError("This chat is already linked") from exc
        return professional_id

    def revoke_professional(self, administrator_chat_id: str, professional_id: str) -> None:
        self._require_admin(administrator_chat_id)
        with self._sessions.begin() as session:
            professional = session.get(Professional, professional_id)
            if professional is None:
                raise ResourceNotFound("Professional not found")
            professional.active = False
            self._audit(
                session,
                "administrator",
                "professional.revoked",
                "professional",
                professional.id,
            )

    def create_patient(
        self,
        chat_id: str,
        *,
        display_name: str,
        alias: str | None = None,
        birth_date: date | None = None,
        template: PatientTemplate = "SOAP",
        guardian_name: str | None = None,
        guardian_relationship: str | None = None,
        guardian_contact: str | None = None,
    ) -> PatientRecord:
        if template not in {"SOAP", "ABC", "FREE"}:
            raise ValueError("Unsupported patient template")
        patient_id = new_id()
        with self._sessions.begin() as session:
            professional = self._require_professional(session, chat_id)
            patient = Patient(
                id=patient_id,
                professional_id=professional.id,
                display_name_enc=self._cipher.encrypt(display_name),
                alias_enc=self._cipher.encrypt(alias),
                birth_date_enc=self._cipher.encrypt(birth_date.isoformat() if birth_date else None),
                template=template,
            )
            session.add(patient)
            session.flush()
            if guardian_name is not None:
                if guardian_relationship is None:
                    raise ValueError(
                        "Guardian relationship is required when a guardian is provided"
                    )
                session.add(
                    Guardian(
                        id=new_id(),
                        patient_id=patient_id,
                        name_enc=self._cipher.encrypt(guardian_name),
                        relationship_enc=self._cipher.encrypt(guardian_relationship),
                        contact_enc=self._cipher.encrypt(guardian_contact),
                    )
                )
            self._audit(session, professional.id, "patient.created", "patient", patient_id)
        return PatientRecord(
            id=patient_id,
            display_name=display_name,
            alias=alias,
            birth_date=birth_date.isoformat() if birth_date else None,
            template=template,
            active=True,
        )

    def list_patients(self, chat_id: str) -> list[PatientRecord]:
        with self._sessions.begin() as session:
            professional = self._require_professional(session, chat_id)
            patients = session.scalars(
                select(Patient)
                .where(Patient.professional_id == professional.id, Patient.active.is_(True))
                .order_by(Patient.created_at, Patient.id)
            ).all()
            self._audit(
                session,
                professional.id,
                "patient.listed",
                "patient_list",
                professional.id,
            )
            return [
                PatientRecord(
                    id=patient.id,
                    display_name=self._cipher.decrypt(patient.display_name_enc) or "",
                    alias=self._cipher.decrypt(patient.alias_enc),
                    birth_date=self._cipher.decrypt(patient.birth_date_enc),
                    template=patient.template,
                    active=patient.active,
                )
                for patient in patients
            ]

    def grant_consent(
        self,
        chat_id: str,
        patient_id: str,
        *,
        terms_version: str,
        purpose: str,
        evidence_ref: str | None = None,
    ) -> str:
        consent_id = new_id()
        with self._sessions.begin() as session:
            professional = self._require_professional(session, chat_id)
            self._owned_patient(session, professional.id, patient_id)
            now = utc_now()
            previous_consents = session.scalars(
                select(Consent).where(
                    Consent.patient_id == patient_id,
                    Consent.revoked_at.is_(None),
                )
            ).all()
            for previous in previous_consents:
                previous.revoked_at = now
                self._audit(
                    session,
                    professional.id,
                    "consent.superseded",
                    "patient",
                    patient_id,
                )
            session.add(
                Consent(
                    id=consent_id,
                    patient_id=patient_id,
                    terms_version=terms_version,
                    purpose_enc=self._cipher.encrypt(purpose),
                    evidence_ref_enc=self._cipher.encrypt(evidence_ref),
                )
            )
            self._audit(session, professional.id, "consent.granted", "patient", patient_id)
        return consent_id

    def revoke_consent(self, chat_id: str, patient_id: str) -> None:
        with self._sessions.begin() as session:
            professional = self._require_professional(session, chat_id)
            self._owned_patient(session, professional.id, patient_id)
            consent = session.scalar(
                select(Consent)
                .where(Consent.patient_id == patient_id, Consent.revoked_at.is_(None))
                .order_by(Consent.granted_at.desc())
                .limit(1)
            )
            if consent is None:
                raise ResourceNotFound("Active consent not found")
            consent.revoked_at = utc_now()
            self._audit(session, professional.id, "consent.revoked", "patient", patient_id)

    def require_processing_consent(self, chat_id: str, patient_id: str) -> str:
        with self._sessions.begin() as session:
            professional = self._require_professional(session, chat_id)
            self._owned_patient(session, professional.id, patient_id)
            consent_id = session.scalar(
                select(Consent.id)
                .where(Consent.patient_id == patient_id, Consent.revoked_at.is_(None))
                .limit(1)
            )
            if consent_id is None:
                raise ConsentRequired("Current consent is required before processing")
            self._audit(session, professional.id, "consent.checked", "patient", patient_id)
            return professional.id

    def create_goal(
        self,
        chat_id: str,
        patient_id: str,
        *,
        description: str,
        area: str,
        indicator_type: IndicatorType,
        mastery_criterion: str,
    ) -> GoalRecord:
        if indicator_type not in {"percentage", "duration", "count", "scale"}:
            raise ValueError("Unsupported goal indicator type")
        goal_id = new_id()
        with self._sessions.begin() as session:
            professional = self._require_professional(session, chat_id)
            self._owned_patient(session, professional.id, patient_id)
            goal = Goal(
                id=goal_id,
                patient_id=patient_id,
                description_enc=self._cipher.encrypt(description),
                area_enc=self._cipher.encrypt(area),
                indicator_type=indicator_type,
                mastery_criterion_enc=self._cipher.encrypt(mastery_criterion),
                status="active",
            )
            session.add(goal)
            self._audit(session, professional.id, "goal.created", "goal", goal_id)
        return GoalRecord(
            id=goal_id,
            description=description,
            area=area,
            indicator_type=indicator_type,
            mastery_criterion=mastery_criterion,
            status="active",
        )

    def list_goals(self, chat_id: str, patient_id: str) -> list[GoalRecord]:
        with self._sessions.begin() as session:
            professional = self._require_professional(session, chat_id)
            self._owned_patient(session, professional.id, patient_id)
            goals = session.scalars(
                select(Goal).where(Goal.patient_id == patient_id).order_by(Goal.id)
            ).all()
            self._audit(session, professional.id, "goal.listed", "patient", patient_id)
            return [
                GoalRecord(
                    id=goal.id,
                    description=self._cipher.decrypt(goal.description_enc) or "",
                    area=self._cipher.decrypt(goal.area_enc) or "",
                    indicator_type=_indicator_type(goal.indicator_type),
                    mastery_criterion=self._cipher.decrypt(goal.mastery_criterion_enc) or "",
                    status=goal.status,
                )
                for goal in goals
            ]

    @staticmethod
    def _owned_patient(session: Session, professional_id: str, patient_id: str) -> Patient:
        patient = session.scalar(
            select(Patient).where(
                Patient.id == patient_id,
                Patient.professional_id == professional_id,
                Patient.active.is_(True),
            )
        )
        if patient is None:
            raise ResourceNotFound("Patient not found")
        return patient


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _indicator_type(value: str) -> IndicatorType:
    match value:
        case "percentage":
            return "percentage"
        case "duration":
            return "duration"
        case "count":
            return "count"
        case "scale":
            return "scale"
        case _:
            raise ValueError("Persisted goal has an unsupported indicator type")
