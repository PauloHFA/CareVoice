# Privacy and security readiness

This checklist is an engineering aid, not a RIPD, legal opinion, or authorization to process
real patient data. The current code has encrypted persistence for identity fields and job
payloads, professional-scoped identity operations, and consent record/check operations. It does
not yet provide a consent-capture interface, documented lawful-basis review, or an end-to-end
clinical workflow.

## Initial data flow

The planned flow is professional → channel adapter → persistent job → local transcription →
structured draft and fidelity checks → professional review → approved version and document.
The first Telegram pilot is restricted to fictitious data. Cloud processing remains disabled by
default.

Audio and text submitted to the current job queue are Fernet-encrypted before persistence. The
queue checks professional ownership and current consent when enqueuing and again before a worker
processes a claimed job. These controls do not yet implement audio-retention cleanup, consent
collection UX, a Telegram handler, or approval/version persistence.

Structured drafts now require source quotes for each claim and measure. The deterministic
verifier checks that quotes occur in the transcript, asserted numbers occur in cited text, and
measure values/units/original expressions are supported. This does **not** prove that prose
paraphrases semantically entail their evidence; never treat a passing report as clinical
validation or a replacement for professional review.

## Data requiring protection

- Audio, transcripts, clinical notes, patient identifiers, measures, and generated documents.
- Guardian names and contact details, consent evidence, professional identifiers, and audit
  metadata.
- Provider credentials, bot tokens, and field-encryption keys.

## Required controls before real data

- Document the lawful basis, purposes, data minimization, retention, data-subject rights, and
  applicable professional record-keeping requirements with qualified counsel/DPO.
- Complete and approve a RIPD and threat model; review changes when a provider or channel changes.
- Decide whether Telegram is acceptable or use an authenticated channel fit for the data.
- Assess each processor's contract, retention, training use, processing region, and international
  transfers; require patient-level consent where applicable in addition to configuration.
- Implement and test authentication, revocation, per-professional data isolation, field encryption,
  key rotation/storage, immutable audit records, deletion/retention, encrypted backups, and restore.
- Verify that logs, errors, temporary files, traces, and provider diagnostics contain no clinical
  content or credentials.

## Threat scenarios to test

- Cross-professional reads/writes or stale access after account revocation.
- Prompt injection in dictated text changing system behavior or output schema.
- Unsupported factual claims, invented measures, or wrong-patient association.
- Exposure through logs, temporary files, exception messages, provider retention, or exports.
- Job retry/duplicate processing creating inconsistent versions or bypassing approval.
- Backup, restore, deletion, or retention behavior violating the approved policy.

## Release gate

Keep `CAREVOICE_REAL_DATA_ENABLED=false` and use fictitious data until the controls above are
implemented, tested, and reviewed. The current setting is only a guardrail and does not by itself
enforce this gate.
