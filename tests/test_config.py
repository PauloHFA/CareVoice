import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr, ValidationError

from carevoice.config import Settings


def test_settings_default_to_local_processing_and_fictitious_data() -> None:
    settings = Settings(_env_file=None)

    assert settings.transcriber == "local"
    assert settings.cloud_processing_enabled is False
    assert settings.real_data_enabled is False
    assert settings.pseudonymize_before_llm is True
    assert settings.audio_retention_days == 0


def test_cloud_transcription_requires_explicit_enablement() -> None:
    with pytest.raises(ValidationError, match="Cloud transcription is disabled"):
        Settings(_env_file=None, transcriber="cloud")


def test_cloud_transcription_can_be_enabled_explicitly() -> None:
    settings = Settings(
        _env_file=None,
        transcriber="cloud",
        cloud_processing_enabled=True,
    )

    assert settings.transcriber == "cloud"


@pytest.mark.parametrize("days", [-1, 31])
def test_audio_retention_is_limited_to_zero_through_thirty_days(days: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, audio_retention_days=days)


def test_invalid_timezone_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Unknown timezone"):
        Settings(_env_file=None, default_timezone="Not/A_Real_Zone")


def test_field_encryption_key_must_be_a_fernet_key() -> None:
    with pytest.raises(ValidationError, match="valid Fernet key"):
        Settings(_env_file=None, field_encryption_key=SecretStr("not-a-key"))


def test_production_requires_encryption_key() -> None:
    with pytest.raises(ValidationError, match="required in production"):
        Settings(_env_file=None, environment="production")


def test_production_rejects_sqlite() -> None:
    with pytest.raises(ValidationError, match="requires PostgreSQL"):
        Settings(
            _env_file=None,
            environment="production",
            field_encryption_key=SecretStr(Fernet.generate_key().decode("ascii")),
            administrator_chat_id=SecretStr("admin"),
        )


def test_production_accepts_postgresql_and_required_keys() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        field_encryption_key=SecretStr(Fernet.generate_key().decode("ascii")),
        administrator_chat_id=SecretStr("admin"),
        database_url=SecretStr("postgresql+psycopg://user:pass@localhost/carevoice"),
    )

    assert settings.environment == "production"
