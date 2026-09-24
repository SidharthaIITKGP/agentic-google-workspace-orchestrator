import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from cryptography.fernet import Fernet

from app.auth.security import CredentialEncryptionError, TokenCipher
from app.core.config import Settings
from app.db.models import GoogleCredential
from app.integrations import google as google_integration


def test_credential_encryption_round_trip_and_wrong_key() -> None:
    cipher = TokenCipher(Fernet.generate_key().decode())
    encrypted = cipher.encrypt("sensitive-token")

    assert encrypted != "sensitive-token"
    assert cipher.decrypt(encrypted) == "sensitive-token"

    wrong_cipher = TokenCipher(Fernet.generate_key().decode())
    try:
        wrong_cipher.decrypt(encrypted)
    except CredentialEncryptionError:
        pass
    else:
        raise AssertionError("Decrypting with a different key must fail")


def test_expired_google_token_is_refreshed_and_encrypted(monkeypatch) -> None:
    async def exercise() -> None:
        cipher = TokenCipher(Fernet.generate_key().decode())
        stored = GoogleCredential(
            user_id=uuid4(),
            encrypted_access_token=cipher.encrypt("old-access"),
            encrypted_refresh_token=cipher.encrypt("refresh"),
            granted_scopes=["scope"],
            token_expiry=datetime.now(timezone.utc) - timedelta(minutes=5),
        )

        class FakeSession:
            flushed = False

            async def scalar(self, statement):
                return stored

            async def flush(self) -> None:
                self.flushed = True

        class FakeCredentials:
            expired = True
            valid = False
            token = "old-access"
            expiry = datetime.now() - timedelta(minutes=5)

            def refresh(self, request) -> None:
                self.token = "new-access"
                self.expiry = datetime.now() + timedelta(hours=1)
                self.expired = False
                self.valid = True

        fake_credentials = FakeCredentials()
        monkeypatch.setattr(
            google_integration,
            "Credentials",
            lambda **kwargs: fake_credentials,
        )
        settings = Settings(
            _env_file=None,
            google_client_id="client",
            google_client_secret="secret",
        )
        session = FakeSession()
        factory = google_integration.GoogleClientFactory(
            session=session,
            user_id=stored.user_id,
            settings=settings,
            cipher=cipher,
        )

        credentials = await factory._load_credentials()

        assert credentials is fake_credentials
        assert cipher.decrypt(stored.encrypted_access_token) == "new-access"
        assert session.flushed is True

    asyncio.run(exercise())
