from collections.abc import Callable
from functools import partial

import httpx
import pytest

import server.stt as stt
from server.config import get_settings
from server.stt import UnreadableAudio, VoiceUnavailable, transcribe


def fake_xai(monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]) -> list[httpx.Request]:
    """Route the module's HTTP calls to a handler instead of the real xAI API."""
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    monkeypatch.setattr(stt.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(record)))
    return requests


@pytest.mark.anyio
async def test_returns_transcript_and_sends_file_last(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = fake_xai(monkeypatch, lambda r: httpx.Response(200, json={"text": "I want a $600 PC."}))

    assert await transcribe(b"audio-bytes", "request.wav") == "I want a $600 PC."

    body = requests[0].content
    assert requests[0].headers["authorization"] == "Bearer test-xai-key"
    assert body.index(b'name="language"') < body.index(b'name="file"')


@pytest.mark.anyio
async def test_undecodable_audio_raises_unreadable_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    error = {"error": 'Failed to decode audio (format=""). Check that the file is a valid audio file.'}
    fake_xai(monkeypatch, lambda r: httpx.Response(400, json=error))

    with pytest.raises(UnreadableAudio, match="couldn't read that audio"):
        await transcribe(b"not audio", "notes.m4a")


@pytest.mark.anyio
async def test_other_400s_are_not_blamed_on_the_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_xai(monkeypatch, lambda r: httpx.Response(400, json={"error": "Incorrect API key provided."}))

    with pytest.raises(httpx.HTTPStatusError):
        await transcribe(b"audio-bytes", "request.wav")


@pytest.mark.anyio
async def test_empty_file_is_rejected_without_calling_xai(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = fake_xai(monkeypatch, lambda r: httpx.Response(200, json={"text": "unused"}))

    with pytest.raises(UnreadableAudio, match="empty"):
        await transcribe(b"", "empty.wav")
    assert requests == []


@pytest.mark.anyio
async def test_missing_xai_key_raises_voice_unavailable_without_calling_xai(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = fake_xai(monkeypatch, lambda r: httpx.Response(200, json={"text": "unused"}))
    # Blank, like the XAI_API_KEY= line copied from .env.example
    monkeypatch.setenv("XAI_API_KEY", "")
    get_settings.cache_clear()

    with pytest.raises(VoiceUnavailable, match="isn't set up"):
        await transcribe(b"audio-bytes", "request.wav")
    assert requests == []
