from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

import httpx
from anthropic import APIError
from apify_client.errors import ApifyApiError
from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile

from server.agent import (
    BuildRejected,
    InvalidResponse,
    SearchFailed,
    build,
    check_compatibility,
    classify_product,
    evaluate,
    find_alternatives,
    find_other_stores,
    plan_checklist,
    replan,
)
from server.demo_cache import cached
from server.models import (
    AlternativesRequest,
    AlternativesResponse,
    BuildResponse,
    ClassifyRequest,
    ClassifyResponse,
    Compatibility,
    CompatibilityRequest,
    EvaluateRequest,
    Evaluation,
    OtherStoresRequest,
    OtherStoresResponse,
    PlanResponse,
    ReplanRequest,
    ReplanResponse,
)
from server.stores import StoreSearchFailed, StoresUnavailable
from server.stt import UnreadableAudio, VoiceUnavailable, transcribe
from server.timing import Timings

app = FastAPI()

TextField = Annotated[str | None, Form()]
AudioField = Annotated[UploadFile | None, File()]


@contextmanager
def agent_errors() -> Iterator[None]:
    """Turn agent failures into the error responses in docs/api-contract.md."""
    try:
        yield
    except BuildRejected as e:
        raise HTTPException(400, str(e)) from e
    except APIError as e:
        raise HTTPException(502, f"Claude request failed: {e.message}") from e
    except ApifyApiError as e:
        raise HTTPException(502, f"Amazon search failed: {e.message}") from e
    except (InvalidResponse, SearchFailed, StoreSearchFailed) as e:
        raise HTTPException(502, str(e)) from e
    except StoresUnavailable as e:
        raise HTTPException(503, str(e)) from e


async def read_request(text: str | None, audio: UploadFile | None, timings: Timings) -> str:
    """The typed request, or what was said in the recording."""
    if (text is None) == (audio is None):
        raise HTTPException(400, "Send either 'text' or 'audio' (exactly one)")

    if audio is not None:
        try:
            with timings.measure("stt"):
                text = await transcribe(await audio.read(), audio.filename or "audio")
        except UnreadableAudio as e:
            raise HTTPException(400, str(e)) from e
        except VoiceUnavailable as e:
            raise HTTPException(503, str(e)) from e
        except httpx.HTTPStatusError as e:
            raise HTTPException(502, f"Could not transcribe audio: {e.response.text}") from e

    if not text or not text.strip():
        raise HTTPException(400, "The request is empty")
    return text.strip()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/build")
async def create_build(response: Response, text: TextField = None, audio: AudioField = None) -> BuildResponse:
    """Build a shopping list from a typed request or a voice recording."""
    timings = Timings()
    with timings.measure("total"):
        request = await read_request(text, audio, timings)
        with agent_errors():
            result = await build(request, timings)

    # Stage durations in ms, shown in browser devtools under Network → Timing
    response.headers["Server-Timing"] = timings.header()
    return result


@app.post("/api/plan")
async def create_plan(response: Response, text: TextField = None, audio: AudioField = None) -> PlanResponse:
    """Turn a typed request or a voice recording into the Evaluate flow's checklist."""
    timings = Timings()
    with timings.measure("total"):
        request = await read_request(text, audio, timings)
        with agent_errors():
            result = await cached("plan", request, PlanResponse, lambda: plan_checklist(request, timings), timings)

    response.headers["Server-Timing"] = timings.header()
    return result


@app.post("/api/replan")
async def update_plan(request: ReplanRequest, response: Response) -> ReplanResponse:
    """Skip the parts the user's products already take care of, and split what's left of the budget."""
    timings = Timings()
    with timings.measure("total"), agent_errors():
        result = await cached("replan", request, ReplanResponse, lambda: replan(request, timings), timings)

    response.headers["Server-Timing"] = timings.header()
    return result


@app.post("/api/classify")
async def classify(request: ClassifyRequest, response: Response) -> ClassifyResponse:
    """Say which part of the plan the product is, for when its title doesn't make that clear."""
    timings = Timings()
    with timings.measure("total"), agent_errors():
        result = await cached(
            "classify", request, ClassifyResponse, lambda: classify_product(request, timings), timings
        )

    response.headers["Server-Timing"] = timings.header()
    return result


@app.post("/api/evaluate")
async def evaluate_product(request: EvaluateRequest, response: Response) -> Evaluation:
    """Score one product for its part of the request and against the user's setup."""
    timings = Timings()
    with timings.measure("total"), agent_errors():
        result = await cached("evaluate", request, Evaluation, lambda: evaluate(request, timings), timings)

    response.headers["Server-Timing"] = timings.header()
    return result


@app.post("/api/alternatives")
async def alternatives(request: AlternativesRequest, response: Response) -> AlternativesResponse:
    """Find up to 3 options for a part that score higher than the product to beat."""
    timings = Timings()
    with timings.measure("total"), agent_errors():
        result = await cached(
            "alternatives", request, AlternativesResponse, lambda: find_alternatives(request, timings), timings
        )

    response.headers["Server-Timing"] = timings.header()
    return result


@app.post("/api/other-stores")
async def other_stores(request: OtherStoresRequest, response: Response) -> OtherStoresResponse:
    """Find the product the shopper is viewing at other stores, cheapest first."""
    timings = Timings()
    # Never replayed from the demo cache: Bright Data's prize rules disqualify a demo that
    # shows saved web data instead of a live search
    with timings.measure("total"), agent_errors():
        result = await find_other_stores(request, timings)

    response.headers["Server-Timing"] = timings.header()
    return result


@app.post("/api/compatibility")
async def compatibility(request: CompatibilityRequest, response: Response) -> Compatibility:
    """Explain whether a set of products works together, e.g. after swapping a part."""
    if len(request.parts) < 2:
        raise HTTPException(400, "Send at least two parts to compare")

    timings = Timings()
    with agent_errors():
        result = await check_compatibility(request.parts, timings)

    response.headers["Server-Timing"] = timings.header()
    return result
