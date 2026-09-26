import asyncio
import json

import httpx
import pytest

from app.llm.laya import LayaDecisionProvider, LayaProviderError


def _routing_response(*, family: str = "gmail_read", gmail: float = 0.94):
    return {
        "answers": {
            "intent_family": {
                "type": "choice", "choice": family, "confidence": 0.91,
                "answer_confidence": 0.93,
                "probabilities": {family: 0.93},
            },
            "needs_gmail": {"type": "noul", "noul": gmail},
            "needs_calendar": {"type": "noul", "noul": 0.03},
            "needs_drive": {"type": "noul", "noul": 0.04},
            "needs_workspace_search": {"type": "noul", "noul": 0.02},
            "can_proceed": {"type": "noul", "noul": 0.98},
        },
        "model": "typed-decisions",
        "usage": {"input_tokens": 31, "output_tokens": 0},
    }


def _provider(response, requests):
    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=response)

    return LayaDecisionProvider(
        base_url="http://laya.test:8000",
        model="typed-decisions",
        transport=httpx.MockTransport(handler),
    )


def test_provider_uses_one_system_one_request_and_reports_metadata() -> None:
    async def exercise() -> None:
        requests = []
        provider = _provider(_routing_response(), requests)
        decision = await provider.route({"request": "Find unread email"})
        await provider.close()

        assert len(requests) == 1
        assert requests[0].url.path == "/v1/systemone"
        payload = json.loads(requests[0].content)
        assert payload["model"] == "typed-decisions"
        assert payload["state"] == {"request": "Find unread email"}
        assert set(payload["questions"]) == {
            "intent_family", "needs_gmail", "needs_calendar", "needs_drive",
            "needs_workspace_search", "can_proceed",
        }
        assert decision.intent_family == "gmail_read"
        assert decision.intent_confidence == 0.93
        assert decision.service_probabilities["gmail"] == 0.94
        assert decision.input_tokens == 31

        assert payload["questions"]["needs_gmail"]["criteria"]["true"]
        assert payload["questions"]["can_proceed"]["criteria"]["false"]

    asyncio.run(exercise())


def test_provider_prefers_answer_confidence_over_choice_entropy() -> None:
    response = _routing_response()
    response["answers"]["intent_family"].update(
        {"confidence": 0.12, "answer_confidence": 0.88}
    )

    async def exercise() -> None:
        provider = _provider(response, [])
        decision = await provider.route({"request": "Find unread email"})
        await provider.close()
        assert decision.intent_confidence == 0.88

    asyncio.run(exercise())


def test_provider_batches_relevance_questions() -> None:
    response = {
        "answers": {
            "candidate_0": {"type": "noul", "noul": 0.2},
            "candidate_1": {"type": "noul", "noul": 0.9},
        },
        "model": "typed-decisions",
        "usage": {"input_tokens": 18, "output_tokens": 0},
    }

    async def exercise() -> None:
        requests = []
        provider = _provider(response, requests)
        decision = await provider.relevance(
            "Project Alpha",
            [
                {"service": "gmail", "title": "Digest", "snippet": "News"},
                {"service": "google_drive", "title": "Alpha", "snippet": "Notes"},
            ],
        )
        await provider.close()
        assert decision.probabilities == [0.2, 0.9]
        questions = json.loads(requests[0].content)["questions"]
        assert set(questions) == {"candidate_0", "candidate_1"}

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "response",
    [
        _routing_response(family="invented-family"),
        _routing_response(gmail=float("nan")),
        _routing_response(gmail=1.5),
    ],
)
def test_provider_rejects_malformed_decisions(response) -> None:
    async def exercise() -> None:
        provider = _provider(response, [])
        with pytest.raises(LayaProviderError, match="unexpected routing response"):
            await provider.route({"request": "Find email"})
        await provider.close()

    asyncio.run(exercise())


def test_provider_http_failure_is_wrapped_for_safe_fallback() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "warming"})

    async def exercise() -> None:
        provider = LayaDecisionProvider(
            base_url="http://laya.test:8000",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(LayaProviderError, match="decision request failed"):
            await provider.route({"request": "Find email"})
        await provider.close()

    asyncio.run(exercise())
