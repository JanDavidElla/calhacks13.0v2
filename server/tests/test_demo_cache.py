from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server.demo_cache as demo_cache
import server.main as main
from server.config import get_settings
from server.demo_cache import cached
from server.main import app
from server.models import (
    EvaluateRequest,
    Evaluation,
    OtherStoresRequest,
    OtherStoresResponse,
    PartChoice,
    Product,
    ScoreCheck,
)
from server.timing import Timings

CPU = Product(asin="B0CPU00001", title="Intel Core i5-13600K", price=219.99, url="https://www.amazon.com/dp/B0CPU00001")
BOARD = Product(asin="B0MOBO0001", title="MSI MAG B650 TOMAHAWK", price=179.99,
                url="https://www.amazon.com/dp/B0MOBO0001")
REQUEST = EvaluateRequest(request="a gaming PC for $600", category="CPU", product=CPU,
                          setup=[PartChoice(category="Motherboard", product=BOARD)], max_price=180)
EVALUATION = Evaluation(score=100, checks=[
    ScoreCheck(kind="reviews", status="pass", parts=["CPU"], reason="Rated 4.7 out of 5.", points=0),
])


@pytest.fixture
def cache_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Turn the demo cache on, saving to a temporary file."""
    path = tmp_path / "demo-cache.json"
    monkeypatch.setattr(demo_cache, "CACHE_FILE", path)
    monkeypatch.setenv("DEMO_CACHE", "true")
    get_settings.cache_clear()
    return path


class Judge:
    """A stand-in for a live call that counts how often it runs."""

    def __init__(self, result: Evaluation = EVALUATION) -> None:
        self.calls = 0
        self.result = result

    async def __call__(self) -> Evaluation:
        self.calls += 1
        return self.result


async def run(request: EvaluateRequest | str, judge: Judge, timings: Timings | None = None) -> Evaluation:
    return await cached("evaluate", request, Evaluation, judge, timings or Timings())


@pytest.mark.anyio
async def test_off_by_default_every_request_runs_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo_cache, "CACHE_FILE", tmp_path / "demo-cache.json")
    judge = Judge()

    await run(REQUEST, judge)
    await run(REQUEST, judge)

    assert judge.calls == 2
    assert not (tmp_path / "demo-cache.json").exists()


@pytest.mark.anyio
async def test_a_repeated_request_replays_the_saved_answer(cache_file: Path) -> None:
    judge = Judge()
    timings = Timings()

    first = await run(REQUEST, judge)
    second = await run(REQUEST, judge, timings)

    assert judge.calls == 1
    assert first == second == EVALUATION
    assert list(timings.durations_ms) == ["cache"]


@pytest.mark.anyio
async def test_saved_answers_survive_a_server_restart(cache_file: Path) -> None:
    await run(REQUEST, Judge())
    judge = Judge()

    await run(REQUEST, judge)  # reads the file, not anything held in memory

    assert judge.calls == 0
    assert cache_file.exists()


@pytest.mark.anyio
async def test_a_changed_price_or_listing_text_still_replays(cache_file: Path) -> None:
    await run(REQUEST, Judge())
    overnight = REQUEST.model_copy(update={"product": CPU.model_copy(update={"price": 209.99, "details": "New text"})})
    judge = Judge()

    await run(overnight, judge)

    assert judge.calls == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    "change",
    [
        {"product": BOARD},
        {"setup": []},
        {"request": "a quiet gaming PC for $600"},
        {"max_price": 200},
    ],
    ids=["another product", "another setup", "another request", "another budget"],
)
async def test_a_different_request_runs_live(cache_file: Path, change: dict[str, object]) -> None:
    await run(REQUEST, Judge())
    judge = Judge()

    await run(REQUEST.model_copy(update=change), judge)

    assert judge.calls == 1


@pytest.mark.anyio
async def test_a_failure_is_never_saved(cache_file: Path) -> None:
    async def fails() -> Evaluation:
        raise RuntimeError("Claude timed out")

    with pytest.raises(RuntimeError):
        await cached("evaluate", REQUEST, Evaluation, fails, Timings())
    judge = Judge()

    await run(REQUEST, judge)

    assert judge.calls == 1


@pytest.mark.anyio
async def test_endpoints_are_saved_separately(cache_file: Path) -> None:
    await run("a gaming PC for $600", Judge())
    judge = Judge()

    await cached("plan", "a gaming PC for $600", Evaluation, judge, Timings())

    assert judge.calls == 1


def test_evaluate_endpoint_replays_with_demo_cache_on(cache_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    judge = Judge()

    async def fake_evaluate(request: EvaluateRequest, timings: Timings) -> Evaluation:
        return await judge()

    monkeypatch.setattr(main, "evaluate", fake_evaluate)
    client = TestClient(app)
    body = REQUEST.model_dump()

    client.post("/api/evaluate", json=body)
    response = client.post("/api/evaluate", json=body)

    assert response.status_code == 200
    assert response.json() == EVALUATION.model_dump()
    assert judge.calls == 1
    assert "cache;dur=" in response.headers["Server-Timing"]


def test_other_stores_always_runs_live_with_demo_cache_on(cache_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    searches = 0

    async def fake_find(request: OtherStoresRequest, timings: Timings) -> OtherStoresResponse:
        nonlocal searches
        searches += 1
        return OtherStoresResponse(offers=[])

    monkeypatch.setattr(main, "find_other_stores", fake_find)
    client = TestClient(app)
    body = {"product": CPU.model_dump()}

    client.post("/api/other-stores", json=body)
    client.post("/api/other-stores", json=body)

    assert searches == 2
    assert not cache_file.exists()
