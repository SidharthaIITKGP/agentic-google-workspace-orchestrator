from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.calendar import CalendarAgent
from app.agents.drive import DriveAgent
from app.agents.gmail import GmailAgent
from app.agents.workspace import WorkspaceSearchAgent
from app.auth.security import TokenCipher
from app.core.config import Settings
from app.core.cache import RedisCache
from app.integrations.google import GoogleClientFactory
from app.orchestration.registry import AgentRegistry
from app.retrieval.embeddings import embedding_provider_from_settings
from app.retrieval.search import HybridWorkspaceSearch


def build_agent_registry(
    session: AsyncSession,
    user_id: UUID,
    settings: Settings,
    cache: RedisCache | None = None,
) -> AgentRegistry:
    clients = GoogleClientFactory(
        session=session,
        user_id=user_id,
        settings=settings,
        cipher=TokenCipher(settings.token_encryption_key),
    )
    gmail = GmailAgent(clients)
    calendar = CalendarAgent(clients)
    drive = DriveAgent(clients)
    return AgentRegistry(
        gmail=gmail,
        calendar=calendar,
        drive=drive,
        workspace=WorkspaceSearchAgent(
            search=HybridWorkspaceSearch(
                session=session,
                embeddings=embedding_provider_from_settings(settings),
                cache=cache,
                cache_ttl_seconds=settings.embedding_cache_ttl_seconds,
            ),
            user_id=user_id,
            settings=settings,
            native_agents={
                "gmail": gmail,
                "google_drive": drive,
            },
        ),
    )
