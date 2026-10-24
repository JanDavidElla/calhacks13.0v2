import json
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

import server.agent as agent
from server.agent import BuildRejected, ask_claude, build, check_compatibility
from server.models import (
    BuildPicks,
    BuildPlan,
    Compatibility,
    CompatibilityCheck,
    PartChoice,
    PartPick,
    PartPlan,
    Product,
)
from server.timing import Timings

PLAN = BuildPlan(
    rejection=None,
    budget=300,
    parts=[
        PartPlan(category="CPU", search_query="ryzen 5", max_price=150),
        PartPlan(category="GPU", search_query="rx 6600", max_price=150),
    ],
)

CANDIDATES = {
    "CPU": [Product(asin="CPU1", title="Ryzen 5 5600", price=99.99, url="https://www.amazon.com/dp/CPU1")],
    "GPU": [Product(asin="GPU1", title="RX 6600", price=149.5, url="https://www.amazon.com/dp/GPU1",
                    image="https://img.example/gpu.jpg")],
}


COMPATIBLE = Compatibility(
    compatible=True,
    checks=[CompatibilityCheck(parts=["CPU", "GPU"], compatible=True, reason="PCIe card fits any AM4 board")],
)


class FakeClaude:
    """Replaces ask_claude: returns a canned response for each schema Claude is asked for."""

    def __init__(
        self,
        plan: BuildPlan | None = None,
        picks: BuildPicks | None = None,
        compatibility: Compatibility | None = None,
    ) -> None:
        self.responses: dict[type[BaseModel], BaseModel | None] = {
            BuildPlan: plan,
            BuildPicks: picks,
            Compatibility: compatibility,
        }
        self.prompts: list[str] = []
        self.efforts: list[str] = []

    async def __call__(
        self, client: Any, effort: str, system: str, user: str, schema: type[BaseModel]
    ) -> BaseModel | None:
        self.prompts.append(user)
        self.efforts.append(effort)
        return self.responses[schema]


def picks(*asins: str) -> BuildPicks:
    return BuildPicks(
        picks=[PartPick(category=asin[:3], asin=asin, reason=f"Good {asin}") for asin in asins],
        summary="A solid build.",
        compatibility=COMPATIBLE,
    )


@pytest.fixture
def searches(monkeypatch: pytest.MonkeyPatch) -> list[list[PartPlan]]:
    """Replace the Amazon search with canned candidates and record each search."""
    calls: list[list[PartPlan]] = []

    async def fake_search(parts: list[PartPlan]) -> dict[str, list[Product]]:
        calls.append(parts)
        return CANDIDATES

    monkeypatch.setattr(agent, "search_parts", fake_search)
    return calls


def use_claude(monkeypatch: pytest.MonkeyPatch, claude: FakeClaude) -> FakeClaude:
    monkeypatch.setattr(agent, "ask_claude", claude)
    return claude


@pytest.mark.anyio
async def test_build_uses_amazon_data_for_picked_products(
    monkeypatch: pytest.MonkeyPatch, searches: list[list[PartPlan]]
) -> None:
    use_claude(monkeypatch, FakeClaude(PLAN, picks("CPU1", "GPU1")))

    result = await build("A $300 PC")

    assert searches == [PLAN.parts]
    assert result.transcript == "A $300 PC"
    assert result.budget == 300
    assert result.summary == "A solid build."
    assert [(p.category, p.product, p.reason) for p in result.parts] == [
        ("CPU", CANDIDATES["CPU"][0], "Good CPU1"),
        ("GPU", CANDIDATES["GPU"][0], "Good GPU1"),
    ]
    assert result.total == 249.49
    assert result.compatibility == COMPATIBLE


@pytest.mark.anyio
async def test_build_drops_asins_claude_made_up(
    monkeypatch: pytest.MonkeyPatch, searches: list[list[PartPlan]]
) -> None:
    use_claude(monkeypatch, FakeClaude(PLAN, picks("CPU1", "FAKE123")))

    result = await build("A $300 PC")

    assert [p.product.asin for p in result.parts] == ["CPU1"]
    assert result.total == 99.99


@pytest.mark.anyio
async def test_build_sends_candidates_without_links_to_claude(
    monkeypatch: pytest.MonkeyPatch, searches: list[list[PartPlan]]
) -> None:
    claude = use_claude(monkeypatch, FakeClaude(PLAN, picks("CPU1")))

    await build("A $300 PC")

    plan_prompt, pick_prompt = claude.prompts
    assert plan_prompt == "A $300 PC"
    assert "Budget: $300.0" in pick_prompt
    candidates = json.loads(pick_prompt.split("Candidates: ", 1)[1])
    assert candidates["GPU"] == [{"asin": "GPU1", "title": "RX 6600", "price": 149.5, "stars": None}]


@pytest.mark.anyio
async def test_build_rejects_before_searching_amazon(
    monkeypatch: pytest.MonkeyPatch, searches: list[list[PartPlan]]
) -> None:
    rejected = BuildPlan(rejection="That's not a shopping request.", budget=0, parts=[])
    use_claude(monkeypatch, FakeClaude(rejected))

    with pytest.raises(BuildRejected, match="not a shopping request"):
        await build("What's the weather?")
    assert searches == []


@pytest.mark.anyio
async def test_build_records_stage_timings(
    monkeypatch: pytest.MonkeyPatch, searches: list[list[PartPlan]]
) -> None:
    use_claude(monkeypatch, FakeClaude(PLAN, picks("CPU1")))
    timings = Timings()

    await build("A $300 PC", timings)

    assert list(timings.durations_ms) == ["plan", "search", "pick"]
    assert all(ms >= 0 for ms in timings.durations_ms.values())


def fake_client(parse: Any) -> Any:
    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse)))


@pytest.mark.anyio
async def test_ask_claude_returns_parsed_output_and_sends_effort() -> None:
    calls: list[dict[str, Any]] = []

    async def parse(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(parsed_output=PLAN)

    result = await ask_claude(fake_client(parse), "low", "system", "A $300 PC", BuildPlan)

    assert result == PLAN
    assert calls[0]["model"] == agent.MODEL
    assert calls[0]["system"] == "system"
    assert calls[0]["messages"] == [{"role": "user", "content": "A $300 PC"}]
    assert calls[0]["output_format"] is BuildPlan
    assert calls[0]["output_config"] == {"effort": "low"}


@pytest.mark.anyio
async def test_ask_claude_raises_when_there_is_no_output() -> None:
    # e.g. Claude and every fallback model declined the request
    async def parse(**kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(parsed_output=None)

    with pytest.raises(RuntimeError, match="did not return a valid response"):
        await ask_claude(fake_client(parse), "low", "system", "user", BuildPlan)


@pytest.mark.anyio
async def test_ask_claude_raises_when_response_does_not_match_schema() -> None:
    async def parse(**kwargs: Any) -> SimpleNamespace:
        BuildPlan.model_validate_json('{"not": "a plan"}')
        raise AssertionError("unreachable")

    with pytest.raises(RuntimeError, match="did not return a valid response"):
        await ask_claude(fake_client(parse), "low", "system", "user", BuildPlan)


@pytest.mark.anyio
async def test_check_compatibility_sends_only_categories_and_titles(monkeypatch: pytest.MonkeyPatch) -> None:
    claude = use_claude(monkeypatch, FakeClaude(compatibility=COMPATIBLE))
    parts = [PartChoice(category=category, product=products[0]) for category, products in CANDIDATES.items()]
    timings = Timings()

    result = await check_compatibility(parts, timings)

    assert result == COMPATIBLE
    assert json.loads(claude.prompts[0].removeprefix("Products: ")) == [
        {"category": "CPU", "title": "Ryzen 5 5600"},
        {"category": "GPU", "title": "RX 6600"},
    ]
    assert list(timings.durations_ms) == ["check"]


@pytest.mark.anyio
async def test_build_searches_at_most_max_items(
    monkeypatch: pytest.MonkeyPatch, searches: list[list[PartPlan]]
) -> None:
    many = [PartPlan(category=f"Item {i}", search_query=f"item {i}", max_price=10) for i in range(12)]
    use_claude(monkeypatch, FakeClaude(PLAN.model_copy(update={"parts": many}), picks("CPU1")))

    await build("Decorate my whole house for Christmas, $120")

    assert searches == [many[: agent.MAX_ITEMS]]


@pytest.mark.anyio
async def test_build_uses_the_configured_effort_for_each_stage(
    monkeypatch: pytest.MonkeyPatch, searches: list[list[PartPlan]]
) -> None:
    monkeypatch.setattr(agent, "PLAN_EFFORT", "plan-effort")
    monkeypatch.setattr(agent, "PICK_EFFORT", "pick-effort")
    claude = use_claude(monkeypatch, FakeClaude(PLAN, picks("CPU1")))

    await build("A $300 PC")

    assert claude.efforts == ["plan-effort", "pick-effort"]
