import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from cryptography.fernet import Fernet

from app.api.routes import auth as auth_routes
from app.auth.security import TokenCipher
from app.core.config import Settings
from app.db.models import GoogleCredential, User


class FakeCache:
    def __init__(self) -> None:
        self.values = {"oauth-state:state": {"valid": True}}

    async def get_json(self, key: str):
        return self.values.get(key)

    async def delete(self, key: str) -> bool:
        return self.values.pop(key, None) is not None

    async def set_json(self, key: str, value, ttl_seconds: int) -> None:
        self.values[key] = value


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = False

    async def scalar(self, statement):
        return None

    def add(self, value: object) -> None:
        if isinstance(value, User) and value.id is None:
            value.id = uuid4()
        self.added.append(value)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True


def test_oauth_callback_encrypts_tokens_and_sets_session(monkeypatch) -> None:
    async def exercise() -> None:
        key = Fernet.generate_key().decode()
        settings = Settings(
            _env_file=None,
            google_client_id="client",
            google_client_secret="secret",
            token_encryption_key=key,
        )

        class Credentials:
            token = "access-token"
            refresh_token = "refresh-token"
            expiry = datetime.now(timezone.utc) + timedelta(hours=1)
            scopes = ["scope"]

        class Flow:
            credentials = Credentials()

            def fetch_token(self, code: str) -> None:
                assert code == "code"

        class UserInfoRequest:
            def execute(self):
                return {"email": "person@example.com"}

        class OAuthService:
            def userinfo(self):
                return self

            def get(self):
                return UserInfoRequest()

        monkeypatch.setattr(auth_routes, "get_settings", lambda: settings)
        monkeypatch.setattr(auth_routes, "_create_flow", lambda state: Flow())
        monkeypatch.setattr(auth_routes, "build", lambda *args, **kwargs: OAuthService())
        session = FakeSession()
        cache = FakeCache()

        response = await auth_routes.google_callback(
            session=session,
            cache=cache,
            code="code",
            state="state",
        )

        stored = next(item for item in session.added if isinstance(item, GoogleCredential))
        cipher = TokenCipher(key)
        assert cipher.decrypt(stored.encrypted_access_token) == "access-token"
        assert cipher.decrypt(stored.encrypted_refresh_token) == "refresh-token"
        assert stored.encrypted_access_token != "access-token"
        assert session.committed is True
        assert "workspace_session=" in response.headers["set-cookie"]
        assert json.loads(response.body)["status"] == "authenticated"

    asyncio.run(exercise())


def test_accept_granted_scope_expansion() -> None:
    class OAuthSession:
        token = {}

    class Flow:
        oauth2session = OAuthSession()

    token = {
        "access_token": "access-token",
        "scope": " ".join([*auth_routes.GOOGLE_SCOPES, "email", "profile"]),
    }
    warning = Warning("scope expanded")
    warning.token = token

    assert auth_routes._accept_granted_scope_expansion(Flow(), warning) is True
    assert Flow.oauth2session.token == token


def test_reject_granted_scope_reduction() -> None:
    class OAuthSession:
        token = {}

    class Flow:
        oauth2session = OAuthSession()

    warning = Warning("scope reduced")
    warning.token = {
        "access_token": "access-token",
        "scope": auth_routes.GOOGLE_SCOPES[0],
    }

    assert auth_routes._accept_granted_scope_expansion(Flow(), warning) is False
    assert Flow.oauth2session.token == {}
