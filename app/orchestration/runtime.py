from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.calendar import CalendarAgent
from app.agents.drive import DriveAgent
from app.agents.gmail import GmailAgent
from app.auth.security import TokenCipher
from app.core.config import Settings
from app.integrations.google import GoogleClientFactory
from app.orchestration.registry import AgentRegistry


def build_agent_registry(
    session: AsyncSession,
    user_id: UUID,
    settings: Settings,
) -> AgentRegistry:
    clients = GoogleClientFactory(
        session=session,
        user_id=user_id,
        settings=settings,
        cipher=TokenCipher(settings.token_encryption_key),
    )
    return AgentRegistry(
        gmail=GmailAgent(clients),
        calendar=CalendarAgent(clients),
        drive=DriveAgent(clients),
    )
