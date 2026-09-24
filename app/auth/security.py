from cryptography.fernet import Fernet, InvalidToken


class CredentialEncryptionError(ValueError):
    pass


class TokenCipher:
    def __init__(self, encryption_key: str) -> None:
        if not encryption_key:
            raise CredentialEncryptionError("TOKEN_ENCRYPTION_KEY is not configured")
        try:
            self._fernet = Fernet(encryption_key.encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise CredentialEncryptionError("TOKEN_ENCRYPTION_KEY is invalid") from exc

    def encrypt(self, token: str) -> str:
        if not token:
            raise CredentialEncryptionError("Cannot encrypt an empty token")
        return self._fernet.encrypt(token.encode("utf-8")).decode("utf-8")

    def decrypt(self, encrypted_token: str) -> str:
        try:
            return self._fernet.decrypt(encrypted_token.encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise CredentialEncryptionError("Stored credential cannot be decrypted") from exc
