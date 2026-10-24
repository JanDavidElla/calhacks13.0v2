import hashlib
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from server.config import get_settings
from server.timing import Timings

# server/demo-cache.json: delete it to record the demo again
CACHE_FILE = Path(__file__).resolve().parents[2] / "demo-cache.json"


def by_asin(value: Any) -> Any:
    """A request body with each product reduced to its ASIN.

    A price or listing text that changes between the rehearsal and the demo still replays.
    """
    if isinstance(value, dict):
        return value["asin"] if "asin" in value else {key: by_asin(item) for key, item in value.items()}
    if isinstance(value, list):
        return [by_asin(item) for item in value]
    return value


def cache_key(endpoint: str, request: BaseModel | str) -> str:
    body = by_asin(request.model_dump()) if isinstance(request, BaseModel) else request
    return f"{endpoint}:{hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()}"


def load() -> dict[str, Any]:
    return json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}


def save(saved: dict[str, Any]) -> None:
    # Write a copy and swap it in, so a crash mid-write can't leave a broken file for the demo
    partial = CACHE_FILE.with_suffix(".tmp")
    partial.write_text(json.dumps(saved, indent=1))
    partial.replace(CACHE_FILE)


async def cached[T: BaseModel](
    endpoint: str,
    request: BaseModel | str,
    schema: type[T],
    compute: Callable[[], Awaitable[T]],
    timings: Timings,
) -> T:
    """With DEMO_CACHE on, replay the saved answer to a request seen before.

    A rehearsed demo then comes back instantly and the same every time. A failure raises
    before anything is saved, so retrying it runs live.
    """
    if not get_settings().demo_cache:
        return await compute()
    key = cache_key(endpoint, request)
    if (hit := load().get(key)) is not None:
        # Marks the replay in Server-Timing, so a rehearsal shows which answers are saved
        with timings.measure("cache"):
            return schema.model_validate(hit)
    result = await compute()
    # Read again: evaluate and alternatives run at the same time, and the other may have saved
    saved = load()
    saved[key] = result.model_dump(mode="json")
    save(saved)
    return result
