# ADR 0001: Initial privacy boundaries

- Status: Accepted for the development foundation
- Decision date: 2026-11-10

## Context

The product handles sensitive health information, including information about children. The
requirements document identifies Telegram bot chats as lacking end-to-end encryption and calls
for explicit review of cloud providers, consent, retention, and legal basis.

## Decisions

- Default transcription mode is local; cloud processing is disabled unless explicitly enabled.
- Real-patient data is disabled by default and is not permitted in the initial Telegram pilot.
- The application package will keep provider implementations behind interfaces as those features
  are added.
- Structured logs redact known sensitive fields. Callers must never place clinical text, names,
  raw exception details, or secrets in free-form log messages.
- This ADR is not a legal determination, consent record, RIPD, or authorization for production use.

## Consequences

- Cloud providers require separate review of contracts, retention, training use, processing
  location, and transfer before activation.
- A production channel decision and legal/privacy review are release gates before real data.
- Settings defaults are safety guardrails, not substitutes for per-patient consent or access
  control, neither of which has been implemented yet.
