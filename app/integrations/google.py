import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import TokenCipher
from app.core.config import Settings
from app.db.models import GoogleCredential

GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive",
]


class GoogleCredentialError(RuntimeError):
    pass


class GoogleClientFactory:
    def __init__(
        self,
        session: AsyncSession,
        user_id: UUID,
        settings: Settings,
        cipher: TokenCipher,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._settings = settings
        self._cipher = cipher
        self._credentials: Credentials | None = None
        self._credential_lock = asyncio.Lock()

    async def build(self, service_name: str, version: str) -> Any:
        credentials = await self._load_credentials()
        return await asyncio.to_thread(
            build,
            service_name,
            version,
            credentials=credentials,
            cache_discovery=False,
        )

    async def _load_credentials(self) -> Credentials:
        async with self._credential_lock:
            if self._credentials is not None and self._credentials.valid:
                return self._credentials

            stored = await self._session.scalar(
                select(GoogleCredential).where(GoogleCredential.user_id == self._user_id)
            )
            if stored is None:
                raise GoogleCredentialError("Google account is not connected")

            expiry = stored.token_expiry
            if expiry.tzinfo is not None:
                expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)
            credentials = Credentials(
                token=self._cipher.decrypt(stored.encrypted_access_token),
                refresh_token=self._cipher.decrypt(stored.encrypted_refresh_token),
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self._settings.google_client_id,
                client_secret=self._settings.google_client_secret,
                scopes=list(stored.granted_scopes),
                expiry=expiry,
            )

            if credentials.expired:
                try:
                    await asyncio.to_thread(credentials.refresh, GoogleAuthRequest())
                except RefreshError as exc:
                    raise GoogleCredentialError(
                        "Google authorization has expired or been revoked"
                    ) from exc
                if not credentials.token or credentials.expiry is None:
                    raise GoogleCredentialError("Google token refresh returned incomplete credentials")
                stored.encrypted_access_token = self._cipher.encrypt(credentials.token)
                stored.token_expiry = _aware_utc(credentials.expiry)
                await self._session.flush()

            self._credentials = credentials
            return credentials


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
