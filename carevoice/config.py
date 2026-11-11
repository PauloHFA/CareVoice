"""Typed application settings with conservative privacy defaults."""

from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.fernet import Fernet, InvalidToken
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings loaded from CAREVOICE_* environment variables or a local .env file."""

    model_config = SettingsConfigDict(
        env_prefix="CAREVOICE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    environment: Literal["development", "test", "production"] = "development"
    transcriber: Literal["local", "cloud"] = "local"
    cloud_processing_enabled: bool = False
    real_data_enabled: bool = False
    pseudonymize_before_llm: bool = True
    default_timezone: str = "America/Fortaleza"
    max_audio_mb: int = Field(default=20, gt=0)
    max_audio_seconds: int = Field(default=300, gt=0)
    audio_retention_days: int = Field(default=0, ge=0, le=30)
    transcript_retention_days: int = Field(default=30, ge=0)
    field_encryption_key: SecretStr | None = None
    telegram_bot_token: SecretStr | None = None
    administrator_chat_id: SecretStr | None = None
    database_url: SecretStr = SecretStr("sqlite:///carevoice.db")

    @field_validator("field_encryption_key")
    @classmethod
    def validate_field_encryption_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            try:
                Fernet(value.get_secret_value().encode("ascii"))
            except (ValueError, UnicodeEncodeError, InvalidToken) as exc:
                raise ValueError("Field encryption key must be a valid Fernet key") from exc
        return value

    @field_validator("default_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown timezone: {value}") from exc
        return value

    @model_validator(mode="after")
    def validate_processing_mode(self) -> "Settings":
        if self.transcriber == "cloud" and not self.cloud_processing_enabled:
            raise ValueError(
                "Cloud transcription is disabled; set CAREVOICE_CLOUD_PROCESSING_ENABLED=true "
                "only after completing the required privacy and provider reviews."
            )
        if self.environment == "production":
            if self.field_encryption_key is None:
                raise ValueError("A field encryption key is required in production")
            if self.database_url.get_secret_value().startswith("sqlite"):
                raise ValueError("Production requires PostgreSQL; SQLite is for development only")
            if self.administrator_chat_id is None:
                raise ValueError("An administrator identity is required in production")
        return self
