"""Authenticated encryption and keyed lookup digests for sensitive values."""

import base64
import hashlib
import hmac
from typing import overload

from cryptography.fernet import Fernet, InvalidToken


class FieldCipher:
    """Encrypts persisted personal data and computes non-reversible lookup digests."""

    def __init__(self, key: str) -> None:
        try:
            key_bytes = key.encode("ascii")
            self._fernet = Fernet(key_bytes)
            raw_key = base64.urlsafe_b64decode(key_bytes)
        except (ValueError, UnicodeEncodeError) as exc:
            raise ValueError("Field encryption key must be a valid Fernet key") from exc
        self._digest_key = hmac.new(raw_key, b"carevoice-lookup-v1", hashlib.sha256).digest()

    @overload
    def encrypt(self, value: str) -> str: ...

    @overload
    def encrypt(self, value: None) -> None: ...

    def encrypt(self, value: str | None) -> str | None:
        if value is None:
            return None
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    @overload
    def decrypt(self, value: str) -> str: ...

    @overload
    def decrypt(self, value: None) -> None: ...

    def decrypt(self, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
            raise ValueError("Unable to decrypt persisted field") from exc

    def encrypt_bytes(self, value: bytes) -> bytes:
        return self._fernet.encrypt(value)

    def decrypt_bytes(self, value: bytes) -> bytes:
        try:
            return self._fernet.decrypt(value)
        except InvalidToken as exc:
            raise ValueError("Unable to decrypt persisted payload") from exc

    def digest(self, value: str) -> str:
        return hmac.new(
            self._digest_key,
            value.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
