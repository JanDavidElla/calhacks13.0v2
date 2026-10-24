from typing import Annotated

import httpx
from apify_client.errors import ApifyApiError
from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from openai import APIError

from server.agent import BuildRejected, build, check_compatibility
from server.models import BuildResponse, Compatibility, CompatibilityRequest
from server.stt import UnreadableAudio, transcribe
from server.timing import Timings

app = FastAPI()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/build")
async def create_build(
    response: Response,
    text: Annotated[str | None, Form()] = None,
    audio: Annotated[UploadFile | None, File()] = None,
) -> BuildResponse:
    """Build a shopping list from a typed request or a voice recording."""
    if (text is None) == (audio is None):
        raise HTTPException(400, "Send either 'text' or 'audio' (exactly one)")

    timings = Timings()
    with timings.measure("total"):
        if audio is not None:
            try:
                with timings.measure("stt"):
                    text = await transcribe(await audio.read(), audio.filename or "audio")
            except UnreadableAudio as e:
                raise HTTPException(400, str(e)) from e
            except httpx.HTTPStatusError as e:
                raise HTTPException(502, f"Could not transcribe audio: {e.response.text}") from e

        if not text or not text.strip():
            raise HTTPException(400, "The request is empty")

        try:
            result = await build(text.strip(), timings)
        except BuildRejected as e:
            raise HTTPException(400, str(e)) from e
        except APIError as e:
            raise HTTPException(502, f"Grok request failed: {e.message}") from e
        except ApifyApiError as e:
            raise HTTPException(502, f"Amazon search failed: {e.message}") from e

    # Stage durations in ms, shown in browser devtools under Network → Timing
    response.headers["Server-Timing"] = timings.header()
    return result


@app.post("/api/compatibility")
async def compatibility(request: CompatibilityRequest, response: Response) -> Compatibility:
    """Explain whether a set of products works together, e.g. after swapping a part."""
    if len(request.parts) < 2:
        raise HTTPException(400, "Send at least two parts to compare")

    timings = Timings()
    try:
        result = await check_compatibility(request.parts, timings)
    except APIError as e:
        raise HTTPException(502, f"Grok request failed: {e.message}") from e

    response.headers["Server-Timing"] = timings.header()
    return result
