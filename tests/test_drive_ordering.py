import asyncio

from app.agents.drive import DriveAgent


class Request:
    def execute(self):
        return {
            "files": [
                {"id": "new", "name": "newest", "modifiedTime": "2026-09-25T03:00:00Z"},
                {"id": "old", "name": "oldest", "modifiedTime": "2026-09-25T01:00:00Z"},
            ]
        }


class DriveService:
    def __init__(self) -> None:
        self.list_arguments = None

    def files(self):
        return self

    def list(self, **kwargs):
        self.list_arguments = kwargs
        return Request()


class ClientFactory:
    def __init__(self, service: DriveService) -> None:
        self.service = service

    async def build(self, service_name: str, version: str):
        return self.service


def test_drive_search_requests_latest_modified_order_and_preserves_it() -> None:
    service = DriveService()
    result = asyncio.run(
        DriveAgent(ClientFactory(service)).execute("search_files", {"max_results": 5})
    )
    assert service.list_arguments["orderBy"] == "modifiedTime desc"
    assert [item["name"] for item in result.data["files"]] == ["newest", "oldest"]
