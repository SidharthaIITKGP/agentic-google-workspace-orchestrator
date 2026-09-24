import asyncio
import logging
import secrets
from collections.abc import Mapping
from datetime import timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse, RedirectResponse
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from sqlalchemy import select

from app.api.dependencies import DatabaseSession, RedisCacheDependency
from app.auth.security import CredentialEncryptionError, TokenCipher
from app.core.config import get_settings
from app.db.models import GoogleCredential, User
from app.integrations.google import GOOGLE_SCOPES

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
logger = logging.getLogger(__name__)


@router.get("/google")
async def google_login(cache: RedisCacheDependency) -> RedirectResponse:
    settings = get_settings()
    _require_oauth_configuration()
    state = secrets.token_urlsafe(32)
    flow = _create_flow(state=state)
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    if not flow.code_verifier:
        raise HTTPException(status_code=500, detail="Google authentication could not be started")
    await cache.set_json(
        f"oauth-state:{state}",
        {"code_verifier": flow.code_verifier},
        ttl_seconds=settings.oauth_state_ttl_seconds,
    )
    return RedirectResponse(authorization_url)


@router.get("/google/callback")
async def google_callback(
    session: DatabaseSession,
    cache: RedisCacheDependency,
    code: str = Query(min_length=1),
    state: str = Query(min_length=1),
) -> JSONResponse:
    settings = get_settings()
    _require_oauth_configuration()
    stored_state = await cache.get_json(f"oauth-state:{state}")
    await cache.delete(f"oauth-state:{state}")
    if not isinstance(stored_state, dict) or not isinstance(
        stored_state.get("code_verifier"), str
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth state is invalid")

    flow = _create_flow(state=state, code_verifier=stored_state["code_verifier"])
    try:
        try:
            await asyncio.to_thread(flow.fetch_token, code=code)
        except Warning as exc:
            if not _accept_granted_scope_expansion(flow, exc):
                raise
        credentials = flow.credentials
        oauth2 = await asyncio.to_thread(
            build,
            "oauth2",
            "v2",
            credentials=credentials,
            cache_discovery=False,
        )
        profile = await asyncio.to_thread(oauth2.userinfo().get().execute)
    except Exception as exc:
        logger.warning(
            "Google OAuth provider exchange failed (%s)",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google authentication failed",
        ) from exc

    email = profile.get("email")
    if not isinstance(email, str) or not email:
        raise HTTPException(status_code=502, detail="Google account did not provide an email")
    if not credentials.token or credentials.expiry is None:
        raise HTTPException(status_code=502, detail="Google returned incomplete credentials")

    try:
        cipher = TokenCipher(settings.token_encryption_key)
    except CredentialEncryptionError as exc:
        raise HTTPException(status_code=503, detail="Credential encryption is not configured") from exc

    user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email)
        session.add(user)
        await session.flush()

    stored_credentials = await session.scalar(
        select(GoogleCredential).where(GoogleCredential.user_id == user.id)
    )
    refresh_token = credentials.refresh_token
    if stored_credentials is None and not refresh_token:
        raise HTTPException(status_code=502, detail="Google did not return a refresh token")

    encrypted_access_token = cipher.encrypt(credentials.token)
    encrypted_refresh_token = (
        cipher.encrypt(refresh_token)
        if refresh_token
        else stored_credentials.encrypted_refresh_token
    )
    expiry = credentials.expiry
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)

    if stored_credentials is None:
        stored_credentials = GoogleCredential(
            user_id=user.id,
            encrypted_access_token=encrypted_access_token,
            encrypted_refresh_token=encrypted_refresh_token,
            granted_scopes=list(credentials.scopes or GOOGLE_SCOPES),
            token_expiry=expiry,
        )
        session.add(stored_credentials)
    else:
        stored_credentials.encrypted_access_token = encrypted_access_token
        stored_credentials.encrypted_refresh_token = encrypted_refresh_token
        stored_credentials.granted_scopes = list(credentials.scopes or GOOGLE_SCOPES)
        stored_credentials.token_expiry = expiry

    await session.commit()
    session_id = secrets.token_urlsafe(32)
    await cache.set_json(
        f"session:{session_id}",
        {"user_id": str(user.id)},
        ttl_seconds=settings.session_ttl_seconds,
    )
    response = JSONResponse({"status": "authenticated", "user_id": str(user.id)})
    response.set_cookie(
        "workspace_session",
        session_id,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.app_env.lower() not in {"development", "test"},
        samesite="lax",
    )
    return response


def _create_flow(state: str, code_verifier: str | None = None) -> Flow:
    settings = get_settings()
    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_redirect_uri],
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=GOOGLE_SCOPES,
        state=state,
        code_verifier=code_verifier,
        autogenerate_code_verifier=code_verifier is None,
    )
    flow.redirect_uri = settings.google_redirect_uri
    return flow


def _require_oauth_configuration() -> None:
    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=503, detail="Google OAuth is not configured")


def _accept_granted_scope_expansion(flow: Flow, exc: Warning) -> bool:
    """Recover when Google grants every requested scope plus additional aliases."""
    token = getattr(exc, "token", None)
    if not isinstance(token, Mapping):
        return False

    granted_scopes = _scope_set(token.get("scope"))
    if not set(GOOGLE_SCOPES).issubset(granted_scopes):
        return False

    flow.oauth2session.token = dict(token)
    logger.info("Google granted an OAuth scope superset; continuing authentication")
    return True


def _scope_set(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(value.split())
    if isinstance(value, (list, tuple, set, frozenset)):
        return {scope for scope in value if isinstance(scope, str)}
    return set()
