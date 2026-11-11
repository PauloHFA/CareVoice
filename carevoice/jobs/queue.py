"""Encrypted persistent job queue with consent checks and bounded retries."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from carevoice.audio.limits import validate_audio_upload
from carevoice.db.models import (
    AuditLog,
    Consent,
    Patient,
    ProcessingJob,
    Professional,
    new_id,
    utc_now,
)
from carevoice.domain.identity import (
    AuthenticationError,
    ConsentRequired,
    IdentityService,
    ResourceNotFound,
)
from carevoice.security.crypto import FieldCipher

JobKind = Literal["audio", "text"]
JobErrorCode = Literal[
    "provider_unavailable",
    "invalid_payload",
    "transcription_failed",
    "consent_revoked",
    "internal_error",
]


class InvalidJobTransition(Exception):
    """Raised when a job cannot move from its current state to the requested state."""


@dataclass(frozen=True)
class ClaimedJob:
    id: str
    professional_id: str
    patient_id: str
    kind: JobKind
    payload: bytes
    attempts: int


class JobQueue:
    """Stores encrypted payloads and exposes short, explicit state transitions."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        identity: IdentityService,
        cipher: FieldCipher,
        *,
        max_audio_mb: int = 20,
        max_audio_seconds: int = 300,
        max_attempts: int = 3,
        base_retry_seconds: int = 2,
    ) -> None:
        if max_audio_mb <= 0 or max_audio_seconds <= 0:
            raise ValueError("Audio limits must be positive")
        if max_attempts <= 0 or max_attempts > 10 or base_retry_seconds <= 0:
            raise ValueError("Retry limits must be positive")
        if base_retry_seconds > 300:
            raise ValueError("Base retry delay cannot exceed 300 seconds")
        self._sessions = sessions
        self._identity = identity
        self._cipher = cipher
        self._max_audio_bytes = max_audio_mb * 1024 * 1024
        self._max_audio_seconds = max_audio_seconds
        self._max_attempts = max_attempts
        self._base_retry_seconds = base_retry_seconds

    def enqueue_audio(
        self,
        chat_id: str,
        patient_id: str,
        *,
        filename: str,
        payload: bytes,
        duration_seconds: float,
        content_type: str | None = None,
    ) -> str:
        audio = validate_audio_upload(
            filename,
            payload,
            duration_seconds,
            max_bytes=self._max_audio_bytes,
            max_duration_seconds=self._max_audio_seconds,
            content_type=content_type,
        )
        return self._enqueue(chat_id, patient_id, "audio", audio.payload)

    def enqueue_text(self, chat_id: str, patient_id: str, text: str) -> str:
        normalized = text.strip()
        if len(normalized) <= 30:
            raise ValueError("Text input must contain more than 30 characters")
        return self._enqueue(chat_id, patient_id, "text", normalized.encode("utf-8"))

    def _enqueue(
        self,
        chat_id: str,
        patient_id: str,
        kind: JobKind,
        payload: bytes,
    ) -> str:
        professional_id = self._identity.require_processing_consent(chat_id, patient_id)
        job_id = str(uuid4())
        with self._sessions.begin() as session:
            professional = session.scalar(
                select(Professional)
                .where(
                    Professional.id == professional_id,
                    Professional.active.is_(True),
                )
                .with_for_update()
            )
            patient = session.scalar(
                select(Patient)
                .where(
                    Patient.id == patient_id,
                    Patient.professional_id == professional_id,
                    Patient.active.is_(True),
                )
                .with_for_update()
            )
            consent = session.scalar(
                select(Consent)
                .where(Consent.patient_id == patient_id, Consent.revoked_at.is_(None))
                .with_for_update()
            )
            if professional is None:
                raise AuthenticationError("Professional access is not active")
            if patient is None:
                raise ResourceNotFound("Patient not found")
            if consent is None:
                raise ConsentRequired("Current consent is required before processing")
            session.add(
                ProcessingJob(
                    id=job_id,
                    professional_id=professional_id,
                    patient_id=patient_id,
                    kind=kind,
                    payload_enc=self._cipher.encrypt_bytes(payload),
                    status="pending",
                    attempts=0,
                    available_at=utc_now(),
                )
            )
            session.add(
                AuditLog(
                    id=new_id(),
                    actor_id=professional_id,
                    action="job.enqueued",
                    object_type="processing_job",
                    object_id=job_id,
                )
            )
        return job_id

    def claim_next(self) -> ClaimedJob | None:
        with self._sessions.begin() as session:
            now = utc_now()
            while True:
                job = session.scalar(
                    select(ProcessingJob)
                    .where(
                        ProcessingJob.status == "pending",
                        ProcessingJob.available_at <= now,
                    )
                    .order_by(ProcessingJob.available_at, ProcessingJob.created_at)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                if job is None:
                    return None
                if not self._job_is_authorized(session, job):
                    job.status = "failed"
                    job.error_code = "consent_revoked"
                    job.completed_at = now
                    session.add(
                        AuditLog(
                            id=new_id(),
                            actor_id=job.professional_id,
                            action="job.failed",
                            object_type="processing_job",
                            object_id=job.id,
                        )
                    )
                    continue
                result = session.execute(
                    update(ProcessingJob)
                    .where(
                        ProcessingJob.id == job.id,
                        ProcessingJob.status == "pending",
                    )
                    .values(
                        status="running",
                        attempts=ProcessingJob.attempts + 1,
                        started_at=now,
                        error_code=None,
                    )
                    .returning(ProcessingJob.id)
                )
                if result.scalar_one_or_none() is None:
                    continue
                session.refresh(job)
                job.error_code = None
                session.add(
                    AuditLog(
                        id=new_id(),
                        actor_id=job.professional_id,
                        action="job.claimed",
                        object_type="processing_job",
                        object_id=job.id,
                    )
                )
                return ClaimedJob(
                    id=job.id,
                    professional_id=job.professional_id,
                    patient_id=job.patient_id,
                    kind=_job_kind(job.kind),
                    payload=self._cipher.decrypt_bytes(job.payload_enc),
                    attempts=job.attempts,
                )

    def assert_claim_is_authorized(self, job_id: str) -> None:
        consent_is_current = True
        with self._sessions.begin() as session:
            job = session.get(ProcessingJob, job_id)
            if job is None or job.status != "running":
                raise ResourceNotFound("Running job not found")
            if not self._job_is_authorized(session, job):
                job.status = "failed"
                job.error_code = "consent_revoked"
                job.completed_at = utc_now()
                session.add(
                    AuditLog(
                        id=new_id(),
                        actor_id=job.professional_id,
                        action="job.failed",
                        object_type="processing_job",
                        object_id=job.id,
                    )
                )
                consent_is_current = False
        if not consent_is_current:
            raise ConsentRequired("Current consent is required before processing")

    def complete(self, job_id: str) -> None:
        with self._sessions.begin() as session:
            job = self._running_job(session, job_id)
            job.status = "completed"
            job.completed_at = utc_now()
            session.add(
                AuditLog(
                    id=new_id(),
                    actor_id=job.professional_id,
                    action="job.completed",
                    object_type="processing_job",
                    object_id=job.id,
                )
            )

    def fail(self, job_id: str, error_code: JobErrorCode) -> bool:
        if error_code not in {
            "provider_unavailable",
            "invalid_payload",
            "transcription_failed",
            "consent_revoked",
            "internal_error",
        }:
            raise ValueError("Unsupported processing error code")
        with self._sessions.begin() as session:
            job = self._running_job(session, job_id)
            now = utc_now()
            job.error_code = error_code
            can_retry = error_code in {
                "provider_unavailable",
                "transcription_failed",
                "internal_error",
            } and job.attempts < self._max_attempts
            if can_retry:
                delay = min(
                    self._base_retry_seconds * 2 ** min(job.attempts - 1, 10),
                    300,
                )
                job.status = "pending"
                job.available_at = now + timedelta(seconds=delay)
                job.started_at = None
            else:
                job.status = "failed"
                job.completed_at = now
            session.add(
                AuditLog(
                    id=new_id(),
                    actor_id=job.professional_id,
                    action="job.retry_scheduled" if can_retry else "job.failed",
                    object_type="processing_job",
                    object_id=job.id,
                )
            )
            return can_retry

    def _job_is_authorized(self, session: Session, job: ProcessingJob) -> bool:
        professional = session.get(Professional, job.professional_id)
        patient = session.get(Patient, job.patient_id)
        if (
            professional is None
            or not professional.active
            or patient is None
            or not patient.active
            or patient.professional_id != professional.id
        ):
            return False
        consent_id = session.scalar(
            select(Consent.id).where(
                Consent.patient_id == job.patient_id,
                Consent.revoked_at.is_(None),
            )
        )
        return consent_id is not None

    @staticmethod
    def _running_job(session: Session, job_id: str) -> ProcessingJob:
        job = session.scalar(
            select(ProcessingJob)
            .where(ProcessingJob.id == job_id, ProcessingJob.status == "running")
            .with_for_update()
        )
        if job is None:
            raise InvalidJobTransition("Job is not running")
        return job


def _job_kind(value: str) -> JobKind:
    match value:
        case "audio":
            return "audio"
        case "text":
            return "text"
        case _:
            raise ValueError("Persisted job has an unsupported kind")
