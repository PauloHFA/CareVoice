import pytest
from cryptography.fernet import Fernet

from carevoice.security.crypto import FieldCipher


def test_cipher_round_trips_sensitive_text_and_uses_randomized_ciphertext() -> None:
    cipher = FieldCipher(Fernet.generate_key().decode("ascii"))

    first = cipher.encrypt("informação sensível")
    second = cipher.encrypt("informação sensível")

    assert first is not None
    assert second is not None
    assert first != second
    assert cipher.decrypt(first) == "informação sensível"
    assert cipher.decrypt(None) is None
    assert cipher.encrypt(None) is None


def test_cipher_digest_is_stable_without_exposing_original() -> None:
    cipher = FieldCipher(Fernet.generate_key().decode("ascii"))

    digest = cipher.digest("private-chat-id")

    assert digest == cipher.digest("private-chat-id")
    assert digest != "private-chat-id"


def test_cipher_rejects_bad_keys_and_tampered_ciphertext() -> None:
    with pytest.raises(ValueError, match="valid Fernet key"):
        FieldCipher("not-a-key")

    cipher = FieldCipher(Fernet.generate_key().decode("ascii"))
    with pytest.raises(ValueError, match="Unable to decrypt"):
        cipher.decrypt("not-valid-ciphertext")
