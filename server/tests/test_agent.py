import json
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

import server.agent as agent
from server.agent import BuildRejected, ask_grok, build, check_compatibility
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


class FakeGrok:
    """Replaces ask_grok: returns a canned response for each schema Grok is asked for."""

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
        self.models: list[str] = []

    async def __call__(
        self, client: Any, model: str, system: str, user: str, schema: type[BaseModel]
    ) -> BaseModel | None:
        self.prompts.append(user)
        self.models.append(model)
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


def use_grok(monkeypatch: pytest.MonkeyPatch, grok: FakeGrok) -> FakeGrok:
    monkeypatch.setattr(agent, "ask_grok", grok)
    return grok


@pytest.mark.anyio
async def test_build_uses_amazon_data_for_picked_products(
    monkeypatch: pytest.MonkeyPatch, searches: list[list[PartPlan]]
) -> None:
    use_grok(monkeypatch, FakeGrok(PLAN, picks("CPU1", "GPU1")))

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
async def test_build_drops_asins_grok_made_up(
    monkeypatch: pytest.MonkeyPatch, searches: list[list[PartPlan]]
) -> None:
    use_grok(monkeypatch, FakeGrok(PLAN, picks("CPU1", "FAKE123")))

    result = await build("A $300 PC")

    assert [p.product.asin for p in result.parts] == ["CPU1"]
    assert result.total == 99.99


@pytest.mark.anyio
async def test_build_sends_candidates_without_links_to_grok(
    monkeypatch: pytest.MonkeyPatch, searches: list[list[PartPlan]]
) -> None:
    grok = use_grok(monkeypatch, FakeGrok(PLAN, picks("CPU1")))

    await build("A $300 PC")

    plan_prompt, pick_prompt = grok.prompts
    assert plan_prompt == "A $300 PC"
    assert "Budget: $300.0" in pick_prompt
    candidates = json.loads(pick_prompt.split("Candidates: ", 1)[1])
    assert candidates["GPU"] == [{"asin": "GPU1", "title": "RX 6600", "price": 149.5, "stars": None}]


@pytest.mark.anyio
async def test_build_rejects_before_searching_amazon(
    monkeypatch: pytest.MonkeyPatch, searches: list[list[PartPlan]]
) -> None:
    rejected = BuildPlan(rejection="That's not a shopping request.", budget=0, parts=[])
    use_grok(monkeypatch, FakeGrok(rejected))

    with pytest.raises(BuildRejected, match="not a shopping request"):
        await build("What's the weather?")
    assert searches == []


@pytest.mark.anyio
async def test_build_records_stage_timings(
    monkeypatch: pytest.MonkeyPatch, searches: list[list[PartPlan]]
) -> None:
    use_grok(monkeypatch, FakeGrok(PLAN, picks("CPU1")))
    timings = Timings()

    await build("A $300 PC", timings)

    assert list(timings.durations_ms) == ["plan", "search", "pick"]
    assert all(ms >= 0 for ms in timings.durations_ms.values())


@pytest.mark.anyio
async def test_ask_grok_raises_when_response_does_not_match_schema() -> None:
    async def parse(**kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=None))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse)))

    with pytest.raises(RuntimeError, match="did not return a valid response"):
        await ask_grok(client, "grok-test", "system", "user", BuildPlan)  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_check_compatibility_sends_only_categories_and_titles(monkeypatch: pytest.MonkeyPatch) -> None:
    grok = use_grok(monkeypatch, FakeGrok(compatibility=COMPATIBLE))
    parts = [PartChoice(category=category, product=products[0]) for category, products in CANDIDATES.items()]
    timings = Timings()

    result = await check_compatibility(parts, timings)

    assert result == COMPATIBLE
    assert json.loads(grok.prompts[0].removeprefix("Products: ")) == [
        {"category": "CPU", "title": "Ryzen 5 5600"},
        {"category": "GPU", "title": "RX 6600"},
    ]
    assert list(timings.durations_ms) == ["check"]


@pytest.mark.anyio
async def test_build_searches_at_most_max_items(
    monkeypatch: pytest.MonkeyPatch, searches: list[list[PartPlan]]
) -> None:
    many = [PartPlan(category=f"Item {i}", search_query=f"item {i}", max_price=10) for i in range(12)]
    use_grok(monkeypatch, FakeGrok(PLAN.model_copy(update={"parts": many}), picks("CPU1")))

    await build("Decorate my whole house for Christmas, $120")

    assert searches == [many[: agent.MAX_ITEMS]]


@pytest.mark.anyio
async def test_build_uses_the_configured_model_for_each_stage(
    monkeypatch: pytest.MonkeyPatch, searches: list[list[PartPlan]]
) -> None:
    monkeypatch.setattr(agent, "PLAN_MODEL", "plan-model")
    monkeypatch.setattr(agent, "PICK_MODEL", "pick-model")
    grok = use_grok(monkeypatch, FakeGrok(PLAN, picks("CPU1")))

    await build("A $300 PC")

    assert grok.models == ["plan-model", "pick-model"]
