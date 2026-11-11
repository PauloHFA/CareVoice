from carevoice.logging import redact_sensitive_fields


def test_redacts_sensitive_fields_recursively() -> None:
    event = {
        "event": "session processed",
        "patient_name": "Example Patient",
        "details": {
            "transcript": "Sensitive clinical text",
            "duration_seconds": 35,
            "records": [{"name": "Example Guardian", "status": "active"}],
        },
    }

    redacted = redact_sensitive_fields(None, "info", event)

    assert redacted["patient_name"] == "[REDACTED]"
    assert redacted["details"]["transcript"] == "[REDACTED]"
    assert redacted["details"]["duration_seconds"] == 35
    assert redacted["details"]["records"][0]["name"] == "[REDACTED]"
    assert redacted["details"]["records"][0]["status"] == "active"


def test_does_not_mutate_original_event() -> None:
    event = {"patient_name": "Example Patient"}

    redacted = redact_sensitive_fields(None, "info", event)

    assert event["patient_name"] == "Example Patient"
    assert redacted["patient_name"] == "[REDACTED]"
