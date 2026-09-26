import asyncio
from datetime import datetime, timezone

import pytest

from app.core.config import Settings
from app.llm.laya import LayaProviderError, LayaRoutingDecision
from app.orchestration.decisions import HybridDecisionEngine
from app.schemas.contracts import Intent, Service


class GroqClassifier:
    def __init__(self, intent: Intent) -> None:
        self.intent = intent
        self.calls = 0

    async def classify(self, *args, **kwargs) -> Intent:
        self.calls += 1
        return self.intent


class LayaProvider:
    def __init__(self, decision: LayaRoutingDecision | None = None, fail: bool = False):
        self.decision = decision
        self.fail = fail
        self.state = None

    async def route(self, state):
        self.state = state
        if self.fail:
            raise LayaProviderError("unavailable")
        return self.decision


class BlockingGroqClassifier(GroqClassifier):
    def __init__(self, intent: Intent, both_started: asyncio.Event) -> None:
        super().__init__(intent)
        self.started = asyncio.Event()
        self.both_started = both_started

    async def classify(self, *args, **kwargs) -> Intent:
        self.started.set()
        await asyncio.wait_for(self.both_started.wait(), timeout=0.5)
        return await super().classify(*args, **kwargs)


class BlockingLayaProvider(LayaProvider):
    def __init__(self, decision: LayaRoutingDecision, both_started: asyncio.Event):
        super().__init__(decision)
        self.started = asyncio.Event()
        self.both_started = both_started

    async def route(self, state):
        self.state = state
        self.started.set()
        await asyncio.wait_for(self.both_started.wait(), timeout=0.5)
        return self.decision


def _decision(**overrides) -> LayaRoutingDecision:
    values = {
        "intent_family": "multi_service_read",
        "intent_confidence": 0.93,
        "service_probabilities": {
            "gmail": 0.96,
            "google_calendar": 0.08,
            "google_drive": 0.94,
            "workspace": 0.91,
        },
        "can_proceed_probability": 0.96,
        "model": "typed-decisions",
        "latency_ms": 12.5,
        "input_tokens": 42,
    }
    values.update(overrides)
    return LayaRoutingDecision(**values)


def _groq_intent(*, clarify: bool = False) -> Intent:
    return Intent(
        intent_name="search_workspace",
        required_services=[Service.GMAIL],
        requires_clarification=clarify,
        clarification_question="Please clarify" if clarify else None,
    )


def test_laya_maps_bounded_family_and_multi_service_selection() -> None:
    async def exercise() -> None:
        engine = HybridDecisionEngine(
            GroqClassifier(_groq_intent()), LayaProvider(_decision()),
            mode="hybrid", minimum_confidence=0.75,
        )
        result = await engine.classify(
            "Find related emails and Drive files", [], datetime.now(timezone.utc), "UTC"
        )
        assert result.metadata.intent_family == "multi_service_read"
        assert result.metadata.decision_provider == "laya"
        assert result.intent.required_services == [
            Service.GMAIL, Service.GOOGLE_DRIVE, Service.WORKSPACE
        ]

    asyncio.run(exercise())


def test_laya_and_groq_classification_start_concurrently() -> None:
    async def exercise() -> None:
        both_started = asyncio.Event()
        groq = BlockingGroqClassifier(_groq_intent(), both_started)
        laya = BlockingLayaProvider(_decision(), both_started)
        task = asyncio.create_task(
            HybridDecisionEngine(
                groq, laya, mode="hybrid", minimum_confidence=0.75
            ).classify("Find related email", [], datetime.now(timezone.utc), "UTC")
        )
        await asyncio.wait_for(groq.started.wait(), timeout=0.5)
        await asyncio.wait_for(laya.started.wait(), timeout=0.5)
        both_started.set()
        await task

    asyncio.run(exercise())


def test_low_confidence_and_provider_failure_fall_back_to_groq() -> None:
    async def exercise() -> None:
        groq_intent = _groq_intent()
        low = _decision(intent_confidence=0.51)
        for provider in (LayaProvider(low), LayaProvider(fail=True)):
            result = await HybridDecisionEngine(
                GroqClassifier(groq_intent), provider,
                mode="hybrid", minimum_confidence=0.75,
            ).classify("Find email", [], datetime.now(timezone.utc), "UTC")
            assert result.intent == groq_intent
            assert result.metadata.decision_provider == "groq_fallback"
            assert result.metadata.fallback_used is True

    asyncio.run(exercise())


def test_laya_never_clears_write_clarification() -> None:
    async def exercise() -> None:
        result = await HybridDecisionEngine(
            GroqClassifier(_groq_intent(clarify=True)),
            LayaProvider(_decision(can_proceed_probability=0.99)),
            mode="laya", minimum_confidence=0.75,
        ).classify(
            "Delete my meeting", [], datetime.now(timezone.utc), "UTC"
        )
        assert result.intent.requires_clarification is True
        assert result.intent.clarification_question == "Please clarify"

    asyncio.run(exercise())


def test_laya_never_clears_imperative_email_write_clarification() -> None:
    async def exercise() -> None:
        intent = _groq_intent(clarify=True).model_copy(
            update={"intent_name": "send_email"}
        )
        result = await HybridDecisionEngine(
            GroqClassifier(intent),
            LayaProvider(_decision(can_proceed_probability=0.99)),
            mode="hybrid",
            minimum_confidence=0.75,
        ).classify(
            "Email John the file", [], datetime.now(timezone.utc), "UTC"
        )
        assert result.intent.requires_clarification is True
        assert result.intent.clarification_question == "Please clarify"

    asyncio.run(exercise())


def test_malformed_laya_decision_falls_back_to_groq() -> None:
    async def exercise() -> None:
        groq_intent = _groq_intent()
        malformed = _decision(
            intent_family="invented_family",
            service_probabilities={"gmail": 2.0},
        )
        result = await HybridDecisionEngine(
            GroqClassifier(groq_intent),
            LayaProvider(malformed),
            mode="hybrid",
            minimum_confidence=0.75,
        ).classify("Find email", [], datetime.now(timezone.utc), "UTC")
        assert result.intent == groq_intent
        assert result.metadata.decision_provider == "groq_fallback"
        assert result.metadata.fallback_used is True

    asyncio.run(exercise())


def test_inconsistent_family_and_service_selection_falls_back() -> None:
    async def exercise() -> None:
        groq_intent = _groq_intent()
        inconsistent = _decision(
            intent_family="calendar_read",
            service_probabilities={
                "gmail": 0.96,
                "google_calendar": 0.04,
                "google_drive": 0.03,
                "workspace": 0.02,
            },
        )
        result = await HybridDecisionEngine(
            GroqClassifier(groq_intent),
            LayaProvider(inconsistent),
            mode="hybrid",
            minimum_confidence=0.75,
        ).classify("Show my calendar", [], datetime.now(timezone.utc), "UTC")
        assert result.intent == groq_intent
        assert result.metadata.decision_provider == "groq_fallback"

    asyncio.run(exercise())


def test_laya_configuration_is_bounded() -> None:
    settings = Settings(
        _env_file=None,
        DECISION_ENGINE="hybrid",
        LAYA_ROUTING_MIN_CONFIDENCE=0.8,
        LAYA_RERANK_CANDIDATES=10,
    )
    assert settings.decision_engine == "hybrid"
    with pytest.raises(ValueError):
        Settings(_env_file=None, LAYA_RERANK_CANDIDATES=100)


def test_routing_context_is_minimized_before_laya_receives_it() -> None:
    async def exercise() -> None:
        provider = LayaProvider(_decision())
        context = [
            {"role": "assistant", "content": "discarded"},
            *[
                {"role": "user", "content": str(index) + ("x" * 2000)}
                for index in range(4)
            ],
        ]
        await HybridDecisionEngine(
            GroqClassifier(_groq_intent()),
            provider,
            mode="hybrid",
            minimum_confidence=0.75,
        ).classify("Find email", context, datetime.now(timezone.utc), "UTC")

        recent = provider.state["recent_context"]
        assert len(recent) == 3
        assert all(len(message["content"]) <= 800 for message in recent)
        assert "discarded" not in str(recent)

    asyncio.run(exercise())
