from collections.abc import Callable
from typing import Any

import httpx
import pytest
from anthropic import APIError
from apify_client.errors import ApifyApiError
from fastapi.testclient import TestClient

import server.main as main
from server.agent import BuildRejected, InvalidResponse, SearchFailed
from server.main import app
from server.models import (
    Alternative,
    AlternativesRequest,
    AlternativesResponse,
    BuildPart,
    BuildResponse,
    ClassifyRequest,
    ClassifyResponse,
    Compatibility,
    CompatibilityCheck,
    EvaluateRequest,
    Evaluation,
    Offer,
    OtherStoresRequest,
    OtherStoresResponse,
    PartChoice,
    PlannedPart,
    PlanResponse,
    Product,
    ReplanRequest,
    ReplanResponse,
    ScoreCheck,
)
from server.stores import StoreSearchFailed, StoresUnavailable
from server.stt import UnreadableAudio, VoiceUnavailable
from server.timing import Timings

client = TestClient(app)

AUDIO = ("request.wav", b"RIFF fake audio", "audio/wav")

COMPATIBLE = Compatibility(
    compatible=True,
    checks=[CompatibilityCheck(parts=["CPU", "Motherboard"], compatible=True, reason="Both use AM4")],
)


def fake_response(request: str) -> BuildResponse:
    product = Product(asin="CPU1", title="Ryzen 5 5600", price=99.99, url="https://www.amazon.com/dp/CPU1")
    return BuildResponse(
        transcript=request,
        budget=300,
        total=99.99,
        summary="A solid build.",
        parts=[BuildPart(category="CPU", product=product, reason="Great value")],
        compatibility=COMPATIBLE,
    )


@pytest.fixture
def builds(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the agent with an instant fake and record each request it receives."""
    requests: list[str] = []

    async def fake_build(request: str, timings: Timings) -> BuildResponse:
        requests.append(request)
        with timings.measure("plan"):
            pass
        return fake_response(request)

    monkeypatch.setattr(main, "build", fake_build)
    return requests


@pytest.fixture
def transcripts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[bytes, str]]:
    """Replace speech to text with a fake that always hears the same sentence."""
    uploads: list[tuple[bytes, str]] = []

    async def fake_transcribe(audio: bytes, filename: str) -> str:
        uploads.append((audio, filename))
        return "I want a $300 PC."

    monkeypatch.setattr(main, "transcribe", fake_transcribe)
    return uploads


def failing_build(error: Exception) -> Callable[..., Any]:
    async def fake_build(request: str, timings: Timings) -> BuildResponse:
        raise error

    return fake_build


def server_timing_stages(response: httpx.Response) -> list[str]:
    return [entry.split(";")[0].strip() for entry in response.headers["server-timing"].split(",")]


def test_text_request_returns_build_in_documented_format(builds: list[str]) -> None:
    response = client.post("/api/build", data={"text": "  I want a $300 PC  "})

    assert response.status_code == 200
    assert builds == ["I want a $300 PC"]
    assert response.json() == fake_response("I want a $300 PC").model_dump()
    assert server_timing_stages(response) == ["plan", "total"]


def test_audio_request_is_transcribed_then_built(
    builds: list[str], transcripts: list[tuple[bytes, str]]
) -> None:
    response = client.post("/api/build", files={"audio": AUDIO})

    assert response.status_code == 200
    assert transcripts == [(b"RIFF fake audio", "request.wav")]
    assert builds == ["I want a $300 PC."]
    assert response.json()["transcript"] == "I want a $300 PC."
    assert server_timing_stages(response) == ["stt", "plan", "total"]


@pytest.mark.parametrize(
    "request_kwargs",
    [{}, {"data": {"text": "hi"}, "files": {"audio": AUDIO}}, {"data": {"text": ""}}],
    ids=["neither", "both", "blank text"],
)
def test_requires_exactly_one_input(builds: list[str], request_kwargs: dict[str, Any]) -> None:
    response = client.post("/api/build", **request_kwargs)

    assert response.status_code == 400
    assert response.json() == {"detail": "Send either 'text' or 'audio' (exactly one)"}
    assert builds == []


def test_silent_audio_is_rejected_as_empty(monkeypatch: pytest.MonkeyPatch, builds: list[str]) -> None:
    async def hears_nothing(audio: bytes, filename: str) -> str:
        return "  "

    monkeypatch.setattr(main, "transcribe", hears_nothing)

    response = client.post("/api/build", files={"audio": AUDIO})

    assert response.status_code == 400
    assert response.json() == {"detail": "The request is empty"}
    assert builds == []


def test_unreadable_audio_returns_400(monkeypatch: pytest.MonkeyPatch, builds: list[str]) -> None:
    async def unreadable(audio: bytes, filename: str) -> str:
        raise UnreadableAudio("We couldn't read that audio file. Try recording again.")

    monkeypatch.setattr(main, "transcribe", unreadable)

    response = client.post("/api/build", files={"audio": AUDIO})

    assert response.status_code == 400
    assert response.json() == {"detail": "We couldn't read that audio file. Try recording again."}
    assert builds == []


def test_voice_without_xai_key_returns_503(monkeypatch: pytest.MonkeyPatch, builds: list[str]) -> None:
    async def no_voice(audio: bytes, filename: str) -> str:
        raise VoiceUnavailable("Voice input isn't set up on this server. Type your request instead.")

    monkeypatch.setattr(main, "transcribe", no_voice)

    response = client.post("/api/build", files={"audio": AUDIO})

    assert response.status_code == 503
    assert response.json() == {"detail": "Voice input isn't set up on this server. Type your request instead."}
    assert builds == []


def test_transcription_failure_returns_502(monkeypatch: pytest.MonkeyPatch, builds: list[str]) -> None:
    async def stt_fails(audio: bytes, filename: str) -> str:
        request = httpx.Request("POST", "https://api.x.ai/v1/stt")
        response = httpx.Response(503, text="Service unavailable", request=request)
        raise httpx.HTTPStatusError("bad audio", request=request, response=response)

    monkeypatch.setattr(main, "transcribe", stt_fails)

    response = client.post("/api/build", files={"audio": AUDIO})

    assert response.status_code == 502
    assert response.json() == {"detail": "Could not transcribe audio: Service unavailable"}
    assert builds == []


def test_rejected_request_returns_400_with_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "build", failing_build(BuildRejected("That's not a shopping request.")))

    response = client.post("/api/build", data={"text": "What's the weather?"})

    assert response.status_code == 400
    assert response.json() == {"detail": "That's not a shopping request."}


@pytest.mark.parametrize(
    ("error", "detail"),
    [
        (
            APIError("Rate limit reached", httpx.Request("POST", "https://api.anthropic.com/v1/messages"), body=None),  # type: ignore[arg-type]
            "Claude request failed: Rate limit reached",
        ),
        (
            ApifyApiError(httpx.Response(402, json={"error": {"message": "Monthly usage hard limit exceeded"}}), 1),  # type: ignore[arg-type]
            "Amazon search failed: Monthly usage hard limit exceeded",
        ),
    ],
    ids=["claude", "apify"],
)
def test_upstream_failures_return_502(monkeypatch: pytest.MonkeyPatch, error: Exception, detail: str) -> None:
    monkeypatch.setattr(main, "build", failing_build(error))

    response = client.post("/api/build", data={"text": "I want a $300 PC"})

    assert response.status_code == 502
    assert response.json() == {"detail": detail}


def test_openapi_documents_build_response_schema() -> None:
    schema = client.get("/openapi.json").json()
    success = schema["paths"]["/api/build"]["post"]["responses"]["200"]
    assert success["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/BuildResponse"}


def build_parts_json() -> list[dict[str, Any]]:
    """Parts exactly as /api/build returns them, including each part's reason."""
    board = Product(asin="MB1", title="MSI B550M AM4", price=89.99, url="https://www.amazon.com/dp/MB1")
    parts = fake_response("A $300 PC").parts + [BuildPart(category="Motherboard", product=board, reason="AM4")]
    return [part.model_dump() for part in parts]


def test_compatibility_accepts_parts_from_a_build_response(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[list[PartChoice]] = []

    async def fake_check(parts: list[PartChoice], timings: Timings) -> Compatibility:
        received.append(parts)
        with timings.measure("check"):
            pass
        return COMPATIBLE

    monkeypatch.setattr(main, "check_compatibility", fake_check)

    response = client.post("/api/compatibility", json={"parts": build_parts_json()})

    assert response.status_code == 200
    assert response.json() == COMPATIBLE.model_dump()
    assert [p.category for p in received[0]] == ["CPU", "Motherboard"]
    assert server_timing_stages(response) == ["check"]


def test_compatibility_needs_at_least_two_parts() -> None:
    response = client.post("/api/compatibility", json={"parts": build_parts_json()[:1]})

    assert response.status_code == 400
    assert response.json() == {"detail": "Send at least two parts to compare"}


def test_compatibility_rejects_malformed_parts() -> None:
    response = client.post("/api/compatibility", json={"parts": [{"category": "CPU"}, {"category": "GPU"}]})

    assert response.status_code == 422


def test_compatibility_claude_failure_returns_502(monkeypatch: pytest.MonkeyPatch) -> None:
    async def claude_fails(parts: list[PartChoice], timings: Timings) -> Compatibility:
        raise APIError("Service unavailable", httpx.Request("POST", "https://api.anthropic.com/v1/messages"), body=None)  # type: ignore[arg-type]

    monkeypatch.setattr(main, "check_compatibility", claude_fails)

    response = client.post("/api/compatibility", json={"parts": build_parts_json()})

    assert response.status_code == 502
    assert response.json() == {"detail": "Claude request failed: Service unavailable"}


PLANNED = PlanResponse(
    transcript="I want a $300 PC.",
    budget=300,
    budget_estimated=False,
    parts=[PlannedPart(category="CPU", search_query="ryzen 5", max_price=150,
                       search_url="https://www.amazon.com/s?k=ryzen+5&rh=p_36%3A-22500")],
)


@pytest.fixture
def plans(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace planning with an instant fake and record each request it receives."""
    requests: list[str] = []

    async def fake_plan(request: str, timings: Timings) -> PlanResponse:
        requests.append(request)
        with timings.measure("plan"):
            pass
        return PLANNED.model_copy(update={"transcript": request})

    monkeypatch.setattr(main, "plan_checklist", fake_plan)
    return requests


def test_plan_returns_the_checklist_in_documented_format(plans: list[str]) -> None:
    response = client.post("/api/plan", data={"text": "  I want a $300 PC.  "})

    assert response.status_code == 200
    assert response.json() == PLANNED.model_dump()
    assert plans == ["I want a $300 PC."]
    assert server_timing_stages(response) == ["plan", "total"]


def test_plan_accepts_voice(plans: list[str], transcripts: list[tuple[bytes, str]]) -> None:
    response = client.post("/api/plan", files={"audio": AUDIO})

    assert response.status_code == 200
    assert response.json()["transcript"] == "I want a $300 PC."
    assert server_timing_stages(response) == ["stt", "plan", "total"]


def test_plan_requires_exactly_one_input(plans: list[str]) -> None:
    response = client.post("/api/plan", data={"text": "a PC"}, files={"audio": AUDIO})

    assert response.status_code == 400
    assert plans == []


def test_too_broad_plan_returns_400_with_the_question(monkeypatch: pytest.MonkeyPatch) -> None:
    async def asks(request: str, timings: Timings) -> PlanResponse:
        raise BuildRejected("Which room are you shopping for?")

    monkeypatch.setattr(main, "plan_checklist", asks)

    response = client.post("/api/plan", data={"text": "Stuff for my house"})

    assert response.status_code == 400
    assert response.json() == {"detail": "Which room are you shopping for?"}


CPU = Product(asin="B0CPU00001", title="Intel Core i5-13600K", price=219.99, url="https://www.amazon.com/dp/B0CPU00001")
BOARD = Product(asin="B0MOBO0001", title="MSI MAG B650 TOMAHAWK", price=179.99,
                url="https://www.amazon.com/dp/B0MOBO0001")
EVALUATE_BODY = {
    "request": "a gaming PC for $600",
    "category": "CPU",
    "product": CPU.model_dump(),
    "setup": [{"category": "Motherboard", "product": BOARD.model_dump()}],
    "max_price": 180,
}
EVALUATION = Evaluation(score=50, checks=[
    ScoreCheck(kind="compatibility", status="fail", parts=["CPU", "Motherboard"], reason="Socket mismatch.",
               points=-40),
    ScoreCheck(kind="budget", status="warn", parts=["CPU"], reason="$39.99 over.", points=-10),
])


def test_evaluate_returns_the_score_in_documented_format(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[EvaluateRequest] = []

    async def fake_evaluate(request: EvaluateRequest, timings: Timings) -> Evaluation:
        received.append(request)
        with timings.measure("check"):
            pass
        return EVALUATION

    monkeypatch.setattr(main, "evaluate", fake_evaluate)

    response = client.post("/api/evaluate", json=EVALUATE_BODY)

    assert response.status_code == 200
    assert response.json() == EVALUATION.model_dump()
    assert received[0].request == "a gaming PC for $600"
    assert [(p.category, p.product.asin) for p in received[0].setup] == [("Motherboard", "B0MOBO0001")]
    assert server_timing_stages(response) == ["check", "total"]


def test_evaluate_needs_only_category_and_product(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[EvaluateRequest] = []

    async def fake_evaluate(request: EvaluateRequest, timings: Timings) -> Evaluation:
        received.append(request)
        return EVALUATION

    monkeypatch.setattr(main, "evaluate", fake_evaluate)

    response = client.post("/api/evaluate", json={"category": "CPU", "product": CPU.model_dump()})

    assert response.status_code == 200
    assert (received[0].request, received[0].setup, received[0].max_price) == (None, [], None)


def test_evaluate_rejects_malformed_products() -> None:
    response = client.post("/api/evaluate", json={"category": "CPU", "product": {"title": "No price"}})

    assert response.status_code == 422


ALTERNATIVES_BODY = {
    "request": "a gaming PC for $600",
    "category": "CPU",
    "search_query": "AMD Ryzen 5 7600 processor",
    "max_price": 180,
    "setup": EVALUATE_BODY["setup"],
    "product": CPU.model_dump(),
}


def test_alternatives_returns_options_in_documented_format(monkeypatch: pytest.MonkeyPatch) -> None:
    ryzen = Product(asin="B0CPU00002", title="AMD Ryzen 5 7600", price=169.0, url="https://www.amazon.com/dp/B0CPU00002")
    found = AlternativesResponse(alternatives=[
        Alternative(product=ryzen, score=100, checks=[], price_difference=-50.99),
    ])
    received: list[AlternativesRequest] = []

    async def fake_alternatives(request: AlternativesRequest, timings: Timings) -> AlternativesResponse:
        received.append(request)
        with timings.measure("search"):
            pass
        with timings.measure("check"):
            pass
        return found

    monkeypatch.setattr(main, "find_alternatives", fake_alternatives)

    response = client.post("/api/alternatives", json=ALTERNATIVES_BODY)

    assert response.status_code == 200
    assert response.json() == found.model_dump()
    assert received[0].product is not None and received[0].product.asin == "B0CPU00001"
    assert server_timing_stages(response) == ["search", "check", "total"]


@pytest.mark.parametrize(
    ("endpoint", "agent_function", "body"),
    [("/api/evaluate", "evaluate", EVALUATE_BODY), ("/api/alternatives", "find_alternatives", ALTERNATIVES_BODY)],
    ids=["evaluate", "alternatives"],
)
@pytest.mark.parametrize(
    ("error", "detail"),
    [
        (
            APIError("Overloaded", httpx.Request("POST", "https://api.anthropic.com/v1/messages"), body=None),  # type: ignore[arg-type]
            "Claude request failed: Overloaded",
        ),
        (InvalidResponse("Claude did not return a valid response"), "Claude did not return a valid response"),
        (
            ApifyApiError(httpx.Response(402, json={"error": {"message": "Monthly usage hard limit exceeded"}}), 1),  # type: ignore[arg-type]
            "Amazon search failed: Monthly usage hard limit exceeded",
        ),
        (SearchFailed("Amazon search found no results for this part. Try again."),
         "Amazon search found no results for this part. Try again."),
    ],
    ids=["claude", "invalid-reply", "apify", "no-results"],
)
def test_evaluate_flow_failures_return_502(
    monkeypatch: pytest.MonkeyPatch, endpoint: str, agent_function: str, body: dict[str, Any],
    error: Exception, detail: str,
) -> None:
    async def fails(request: Any, timings: Timings) -> Any:
        raise error

    monkeypatch.setattr(main, agent_function, fails)

    response = client.post(endpoint, json=body)

    assert response.status_code == 502
    assert response.json() == {"detail": detail}


REPLAN_BODY = {
    "request": "a desk setup for $1,500",
    "budget": 1500,
    "parts": [{"category": "Monitor", "search_query": "27 inch monitor", "max_price": 280},
              {"category": "Desk", "search_query": "standing desk", "max_price": 400}],
    "setup": [{"category": "CPU", "product": CPU.model_dump()}],
}


def test_replan_returns_the_plan_update_in_documented_format(monkeypatch: pytest.MonkeyPatch) -> None:
    updated = ReplanResponse(
        parts=[PlannedPart(category="Desk", search_query="standing desk", max_price=380,
                           search_url="https://www.amazon.com/s?k=standing+desk")],
        filled=[],
        not_needed=[],
        remaining=1280.01,
    )
    received: list[ReplanRequest] = []

    async def fake_replan(request: ReplanRequest, timings: Timings) -> ReplanResponse:
        received.append(request)
        with timings.measure("check"):
            pass
        return updated

    monkeypatch.setattr(main, "replan", fake_replan)

    response = client.post("/api/replan", json=REPLAN_BODY)

    assert response.status_code == 200
    assert response.json() == updated.model_dump()
    assert (received[0].budget, [p.category for p in received[0].parts]) == (1500, ["Monitor", "Desk"])
    assert server_timing_stages(response) == ["check", "total"]


def test_replan_needs_a_budget() -> None:
    response = client.post("/api/replan", json={k: v for k, v in REPLAN_BODY.items() if k != "budget"})

    assert response.status_code == 422


CLASSIFY_BODY = {
    "request": "a desk setup for $800",
    "product": {"asin": "MOUSE1", "title": "Lekvey Ergonomic Mouse, Wireless Vertical Mouse for Office",
                "price": 19.99, "url": "https://www.amazon.com/dp/MOUSE1"},
    "parts": [{"category": "Office chair", "search_query": "ergonomic office chair", "max_price": 200},
              {"category": "Keyboard and mouse", "search_query": "wireless keyboard and mouse", "max_price": 50}],
}


@pytest.mark.parametrize("category", ["Keyboard and mouse", None], ids=["a-part", "none-of-them"])
def test_classify_returns_the_part_in_documented_format(
    monkeypatch: pytest.MonkeyPatch, category: str | None
) -> None:
    received: list[ClassifyRequest] = []

    async def fake_classify(request: ClassifyRequest, timings: Timings) -> ClassifyResponse:
        received.append(request)
        with timings.measure("classify"):
            pass
        return ClassifyResponse(category=category)

    monkeypatch.setattr(main, "classify_product", fake_classify)

    response = client.post("/api/classify", json=CLASSIFY_BODY)

    assert response.status_code == 200
    assert response.json() == {"category": category}
    assert [p.category for p in received[0].parts] == ["Office chair", "Keyboard and mouse"]
    assert server_timing_stages(response) == ["classify", "total"]


def test_classify_needs_the_plan_parts() -> None:
    response = client.post("/api/classify", json={k: v for k, v in CLASSIFY_BODY.items() if k != "parts"})

    assert response.status_code == 422


RYZEN_JSON = {"asin": "B09VCJ171S", "title": "AMD Ryzen 5 5500", "price": 104.0, "url": "https://www.amazon.com/dp/B09VCJ171S"}


def test_other_stores_returns_offers_cheapest_first(monkeypatch: pytest.MonkeyPatch) -> None:
    newegg = Offer(store="Newegg", title="AMD Ryzen 5 5500", price=99.0, url="https://www.google.com/search?q=r5")

    async def fake_find(request: OtherStoresRequest, timings: Timings) -> OtherStoresResponse:
        assert request.product.asin == "B09VCJ171S"
        return OtherStoresResponse(offers=[newegg])

    monkeypatch.setattr(main, "find_other_stores", fake_find)

    response = client.post("/api/other-stores", json={"product": RYZEN_JSON})

    assert response.status_code == 200
    assert response.json() == {"offers": [newegg.model_dump()]}


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (StoresUnavailable("Price checks at other stores aren't set up on this server."), 503),
        (StoreSearchFailed("Google Shopping search failed (captcha). Try again."), 502),
    ],
    ids=["no-key", "search-failed"],
)
def test_other_stores_failures(monkeypatch: pytest.MonkeyPatch, error: Exception, status: int) -> None:
    async def fails(request: OtherStoresRequest, timings: Timings) -> OtherStoresResponse:
        raise error

    monkeypatch.setattr(main, "find_other_stores", fails)

    response = client.post("/api/other-stores", json={"product": RYZEN_JSON})

    assert response.status_code == status
    assert response.json() == {"detail": str(error)}
