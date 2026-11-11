"""Structured logging helpers that redact sensitive fields."""

from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog

_REDACTED = "[REDACTED]"
_SENSITIVE_FIELDS = frozenset(
    {
        "audio",
        "clinical_content",
        "contact",
        "guardian_name",
        "name",
        "patient",
        "patient_name",
        "transcript",
        "transcription",
    }
)


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _REDACTED if str(key).casefold() in _SENSITIVE_FIELDS else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value


def redact_sensitive_fields(
    logger: Any,
    method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Redact known sensitive structured fields before a log event is rendered."""
    del logger, method_name
    return {
        key: _REDACTED if str(key).casefold() in _SENSITIVE_FIELDS else _redact(value)
        for key, value in event_dict.items()
    }


def configure_logging() -> None:
    """Configure JSON logs with sensitive-field redaction."""
    structlog.configure(
        processors=[
            redact_sensitive_fields,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
