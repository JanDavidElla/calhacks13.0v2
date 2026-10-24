import httpx

from server.config import get_settings

STT_URL = "https://api.x.ai/v1/stt"

# xAI also answers 400 for a bad API key, so match the decode message, not just the status
DECODE_ERROR = "Failed to decode audio"


class UnreadableAudio(Exception):
    """The uploaded file is empty or isn't audio xAI can decode."""


class VoiceUnavailable(Exception):
    """The server has no xAI key, so it can't transcribe audio."""


async def transcribe(audio: bytes, filename: str) -> str:
    """Transcribe English speech with xAI Speech to Text."""
    settings = get_settings()
    # An empty XAI_API_KEY= line in .env counts as not set
    if not settings.xai_api_key:
        raise VoiceUnavailable("Voice input isn't set up on this server. Type your request instead.")
    if not audio:
        raise UnreadableAudio("The audio file is empty")

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            STT_URL,
            headers={"Authorization": f"Bearer {settings.xai_api_key}"},
            # xAI requires the file to come after all other form fields
            data={"language": "en", "format": "true"},
            files={"file": (filename, audio)},
        )
    if response.status_code == 400 and DECODE_ERROR in response.text:
        raise UnreadableAudio("We couldn't read that audio file. Try recording again.")
    response.raise_for_status()
    return response.json()["text"]
