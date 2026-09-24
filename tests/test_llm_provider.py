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
