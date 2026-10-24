from collections.abc import Callable
from typing import Any

import httpx
import pytest
from anthropic import APIError
from apify_client.errors import ApifyApiError
from fastapi.testclient import TestClient

import server.main as main
from server.agent import BuildRejected
from server.main import app
from server.models import BuildPart, BuildResponse, Compatibility, CompatibilityCheck, PartChoice, Product
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
