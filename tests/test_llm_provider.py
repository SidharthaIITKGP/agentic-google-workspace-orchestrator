import asyncio
from types import SimpleNamespace

from app.core.config import Settings
from app.llm import provider as provider_module


def test_groq_provider_uses_openai_compatible_endpoint(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(provider_module, "AsyncOpenAI", FakeClient)
    settings = Settings(
        _env_file=None,
        groq_api_key="test-key",
        groq_model="test-model",
    )

    provider = provider_module.GroqProvider(settings)

    assert provider._model == "test-model"
    assert captured["api_key"] == "test-key"
    assert captured["base_url"] == "https://api.groq.com/openai/v1"


def test_groq_provider_explicitly_requests_json(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Completions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
            )

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            self.chat = SimpleNamespace(completions=Completions())

    monkeypatch.setattr(provider_module, "AsyncOpenAI", FakeClient)
    provider = provider_module.GroqProvider(
        Settings(_env_file=None, groq_api_key="test-key", groq_model="test-model")
    )

    result = asyncio.run(provider.generate_json("Plan the request.", {"query": "test"}))

    assert result == {"ok": True}
    assert "JSON" in captured["messages"][0]["content"]
    assert captured["response_format"] == {"type": "json_object"}
