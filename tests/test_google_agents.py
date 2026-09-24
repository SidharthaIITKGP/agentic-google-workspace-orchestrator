import asyncio

from app.agents.calendar import CalendarAgent
from app.agents.drive import DriveAgent
from app.agents.gmail import GmailAgent
from app.schemas.contracts import ExecutionStatus


class Request:
    def __init__(self, response):
        self.response = response

    def execute(self):
        return self.response


class ClientFactory:
    def __init__(self, service) -> None:
        self.service = service

    async def build(self, service_name: str, version: str):
        return self.service


class GmailService:
    def users(self):
        return self

    def messages(self):
        return self

    def list(self, **kwargs):
        return Request({"messages": [{"id": "m1"}]})

    def get(self, **kwargs):
        return Request(
            {
                "id": "m1",
                "threadId": "t1",
                "snippet": "Budget preview",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Budget"},
                        {"name": "From", "value": "sarah@company.com"},
                    ]
                },
            }
        )


class CalendarService:
    def events(self):
        return self

    def get(self, **kwargs):
        return Request(
            {
                "id": "event-1",
                "summary": "Acme meeting",
                "start": {"dateTime": "2026-09-25T10:00:00+00:00"},
                "end": {"dateTime": "2026-09-25T11:00:00+00:00"},
            }
        )


class DriveService:
    def files(self):
        return self

    def list(self, **kwargs):
        return Request(
            {
                "files": [
                    {
                        "id": "file-1",
                        "name": "proposal.pdf",
                        "mimeType": "application/pdf",
                    }
                ]
            }
        )


def test_gmail_agent_returns_structured_search_results() -> None:
    result = asyncio.run(
        GmailAgent(ClientFactory(GmailService())).execute(
            "search_emails", {"sender": "sarah@company.com"}
        )
    )

    assert result.status == ExecutionStatus.COMPLETED
    assert result.data["emails"][0]["subject"] == "Budget"
    assert result.source_ids == ["m1"]


def test_calendar_agent_returns_structured_event() -> None:
    result = asyncio.run(
        CalendarAgent(ClientFactory(CalendarService())).execute(
            "get_event", {"event_id": "event-1"}
        )
    )

    assert result.status == ExecutionStatus.COMPLETED
    assert result.data["event"]["title"] == "Acme meeting"


def test_drive_agent_returns_pdf_metadata_without_extraction() -> None:
    result = asyncio.run(
        DriveAgent(ClientFactory(DriveService())).execute(
            "search_files", {"mime_type": "application/pdf"}
        )
    )

    assert result.status == ExecutionStatus.COMPLETED
    assert result.data["files"][0]["name"] == "proposal.pdf"
