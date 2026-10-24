import httpx

from server.config import get_settings

STT_URL = "https://api.x.ai/v1/stt"

# xAI also answers 400 for a bad API key, so match the decode message, not just the status
DECODE_ERROR = "Failed to decode audio"


class UnreadableAudio(Exception):
    """The uploaded file is empty or isn't audio xAI can decode."""


async def transcribe(audio: bytes, filename: str) -> str:
    """Transcribe English speech with xAI Speech to Text."""
    if not audio:
        raise UnreadableAudio("The audio file is empty")

    settings = get_settings()
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
