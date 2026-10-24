import json
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

import server.agent as agent
from server.agent import (
    BuildRejected,
    InvalidResponse,
    SearchFailed,
    ask_claude,
    build,
    check_compatibility,
    evaluate,
    find_alternatives,
    plan_checklist,
)
from server.amazon import search_url
from server.models import (
    AlternativesRequest,
    BuildPicks,
    BuildPlan,
    CandidateVerdict,
    CandidateVerdicts,
    Compatibility,
    CompatibilityCheck,
    EvaluateRequest,
    Fit,
    FitCheck,
    Match,
    MatchCheck,
    PartChoice,
    PartPick,
    PartPlan,
    Product,
    Verdict,
)
from server.timing import Timings

PLAN = BuildPlan(
    rejection=None,
    budget=300,
    budget_estimated=False,
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
        verdict: Verdict | None = None,
        candidate_verdicts: CandidateVerdicts | None = None,
    ) -> None:
        self.responses: dict[type[BaseModel], BaseModel | None] = {
            BuildPlan: plan,
            BuildPicks: picks,
            Compatibility: compatibility,
            Verdict: verdict,
            CandidateVerdicts: candidate_verdicts,
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
    rejected = BuildPlan(rejection="That's not a shopping request.", budget=0, budget_estimated=False, parts=[])
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

    with pytest.raises(InvalidResponse, match="did not return a valid response"):
        await ask_claude(fake_client(parse), "low", "system", "user", BuildPlan)


@pytest.mark.anyio
async def test_ask_claude_raises_when_response_does_not_match_schema() -> None:
    async def parse(**kwargs: Any) -> SimpleNamespace:
        BuildPlan.model_validate_json('{"not": "a plan"}')
        raise AssertionError("unreachable")

    with pytest.raises(InvalidResponse, match="did not return a valid response"):
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


@pytest.mark.anyio
async def test_plan_checklist_adds_a_budget_filtered_search_link_per_part(
    monkeypatch: pytest.MonkeyPatch, searches: list[list[PartPlan]]
) -> None:
    use_claude(monkeypatch, FakeClaude(PLAN))
    timings = Timings()

    result = await plan_checklist("A $300 PC", timings)

    assert (result.transcript, result.budget, result.budget_estimated) == ("A $300 PC", 300, False)
    assert [(p.category, p.max_price, p.search_url) for p in result.parts] == [
        ("CPU", 150, search_url("ryzen 5", 150)),
        ("GPU", 150, search_url("rx 6600", 150)),
    ]
    assert searches == []  # the user searches Amazon from the links instead
    assert list(timings.durations_ms) == ["plan"]


@pytest.mark.anyio
async def test_plan_checklist_says_when_claude_chose_the_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    use_claude(monkeypatch, FakeClaude(PLAN.model_copy(update={"budget_estimated": True})))

    result = await plan_checklist("A gaming PC")

    assert result.budget_estimated is True


@pytest.mark.anyio
async def test_plan_checklist_rejects_like_build(monkeypatch: pytest.MonkeyPatch) -> None:
    # Too broad requests come back the same way, with a question as the rejection
    question = BuildPlan(rejection="Which room are you shopping for?", budget=0, budget_estimated=True, parts=[])
    use_claude(monkeypatch, FakeClaude(question))

    with pytest.raises(BuildRejected, match="Which room are you shopping for?"):
        await plan_checklist("Stuff for my house")


@pytest.mark.anyio
async def test_plan_checklist_lists_at_most_max_items(monkeypatch: pytest.MonkeyPatch) -> None:
    many = [PartPlan(category=f"Item {i}", search_query=f"item {i}", max_price=10) for i in range(12)]
    use_claude(monkeypatch, FakeClaude(PLAN.model_copy(update={"parts": many})))

    result = await plan_checklist("Decorate my whole house for Christmas, $120")

    assert len(result.parts) == agent.MAX_ITEMS


def product(asin: str, price: float, stars: float | None = 4.5, details: str | None = None) -> Product:
    return Product(asin=asin, title=f"Product {asin}", price=price, url=f"https://www.amazon.com/dp/{asin}",
                   stars=stars, details=details)


def fit(result: Fit, parts: tuple[str, ...] = ("CPU", "Motherboard")) -> FitCheck:
    return FitCheck(parts=list(parts), result=result, reason=f"Result: {result}.")


def match(result: Match = "matches") -> MatchCheck:
    return MatchCheck(result=result, reason=f"Match: {result}.")


REQUEST = "a gaming PC for $600"
BOARD = PartChoice(category="Motherboard", product=product("MOBO1", 179.99, details="Socket AM5. DDR5."))
RAM = PartChoice(category="RAM", product=product("RAM1", 89.99))
# 50 against BOARD with a $180 budget: a socket conflict (-40), and $39.99 over budget (-10)
I5 = product("I5", 219.99, stars=4.7, details="Socket LGA 1700.")


@pytest.mark.anyio
async def test_evaluate_scores_claudes_verdict_in_code(monkeypatch: pytest.MonkeyPatch) -> None:
    claude = use_claude(monkeypatch, FakeClaude(verdict=Verdict(match=match(), checks=[fit("conflict")])))
    timings = Timings()
    request = EvaluateRequest(request=REQUEST, category="CPU", product=I5, setup=[BOARD, RAM], max_price=180)

    result = await evaluate(request, timings)

    assert result.score == 50
    assert [(c.kind, c.status, c.parts) for c in result.checks] == [
        ("match", "pass", ["CPU"]),
        ("compatibility", "fail", ["CPU", "Motherboard"]),
        ("budget", "warn", ["CPU"]),
        ("reviews", "pass", ["CPU"]),
    ]
    assert claude.efforts == [agent.PICK_EFFORT]
    assert list(timings.durations_ms) == ["check"]


@pytest.mark.anyio
async def test_evaluate_ignores_checks_that_leave_out_the_product(monkeypatch: pytest.MonkeyPatch) -> None:
    between_setup_items = fit("conflict", ("Motherboard", "RAM"))
    use_claude(monkeypatch, FakeClaude(verdict=Verdict(match=match(), checks=[fit("fits"), between_setup_items])))

    result = await evaluate(EvaluateRequest(category="CPU", product=I5, setup=[BOARD, RAM]))

    assert [c.parts for c in result.checks if c.kind == "compatibility"] == [["CPU", "Motherboard"]]
    assert result.score == 100


@pytest.mark.anyio
async def test_evaluate_sends_the_request_and_listings_without_prices_or_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claude = use_claude(monkeypatch, FakeClaude(verdict=Verdict(match=match(), checks=[])))

    await evaluate(EvaluateRequest(request=REQUEST, category="CPU", product=I5, setup=[BOARD, RAM]))

    request_line, product_line, setup_line = claude.prompts[0].split("\n")
    assert request_line == f"Request: {REQUEST}"
    assert json.loads(product_line.removeprefix("Product: ")) == {
        "category": "CPU", "title": "Product I5", "details": "Socket LGA 1700.",
    }
    assert json.loads(setup_line.removeprefix("Setup: ")) == [
        {"category": "Motherboard", "title": "Product MOBO1", "details": "Socket AM5. DDR5."},
        {"category": "RAM", "title": "Product RAM1"},  # no details on the listing
    ]


@pytest.mark.anyio
async def test_evaluate_without_a_request_judges_the_part_only(monkeypatch: pytest.MonkeyPatch) -> None:
    claude = use_claude(monkeypatch, FakeClaude(verdict=Verdict(match=match(), checks=[])))

    await evaluate(EvaluateRequest(category="CPU", product=I5, setup=[BOARD]))

    assert claude.prompts[0].startswith("Product: ")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "setup",
    [[], [PartChoice(category="CPU", product=product("OLDCPU", 150))]],
    ids=["empty setup", "only the part it would replace"],
)
async def test_evaluate_scores_the_first_product_on_match_price_and_reviews(
    monkeypatch: pytest.MonkeyPatch, setup: list[PartChoice]
) -> None:
    claude = use_claude(monkeypatch, FakeClaude(verdict=Verdict(match=match("unconfirmed"), checks=[])))

    result = await evaluate(EvaluateRequest(request=REQUEST, category="CPU", product=I5, setup=setup, max_price=180))

    assert claude.prompts[0].endswith("Setup: []")
    assert [(c.kind, c.points) for c in result.checks] == [("match", -10), ("budget", -10), ("reviews", 0)]
    assert result.score == 80


CPU_PART = {"request": REQUEST, "category": "CPU", "search_query": "ryzen 5 am5", "max_price": 180}
R7700 = product("R7700", 175, stars=4.8)
R7600 = product("R7600", 169, stars=4.8)
R5600 = product("R5600", 99, stars=4.6)  # an AM4 CPU
CHEAP = product("CHEAP", 120, stars=3.0)
# The search finds the product to beat again too
FOUND = [R7700, I5, R7600, R5600, CHEAP]


def judged(mismatches: tuple[str, ...] = (), **results: Fit) -> CandidateVerdicts:
    return CandidateVerdicts(candidates=[
        CandidateVerdict(asin=asin, match=match("mismatch" if asin in mismatches else "matches"),
                         checks=[fit(result)])
        for asin, result in results.items()
    ])


# Scores against BOARD: R7700 100, I5 50, R7600 100, R5600 60, CHEAP 85 (poor reviews)
ALL_JUDGED = judged(R7700="fits", I5="conflict", R7600="fits", R5600="conflict", CHEAP="fits")


def use_search(monkeypatch: pytest.MonkeyPatch, found: list[Product]) -> list[list[PartPlan]]:
    """Make every Amazon search find these products, and record each search."""
    calls: list[list[PartPlan]] = []

    async def fake_search(parts: list[PartPlan]) -> dict[str, list[Product]]:
        calls.append(parts)
        return {part.category: found for part in parts}

    monkeypatch.setattr(agent, "search_parts", fake_search)
    return calls


@pytest.mark.anyio
async def test_find_alternatives_returns_the_top_three_that_beat_the_product(monkeypatch: pytest.MonkeyPatch) -> None:
    searches = use_search(monkeypatch, FOUND)
    use_claude(monkeypatch, FakeClaude(candidate_verdicts=ALL_JUDGED))
    request = AlternativesRequest(**CPU_PART, setup=[BOARD], product=I5)
    timings = Timings()

    result = await find_alternatives(request, timings)

    assert searches == [[request]]
    assert [(a.product.asin, a.score, a.price_difference) for a in result.alternatives] == [
        ("R7600", 100, -50.99),  # ties go to the cheaper option
        ("R7700", 100, -44.99),
        ("CHEAP", 85, -99.99),
    ]
    assert [c.kind for c in result.alternatives[0].checks] == ["match", "compatibility", "budget", "reviews"]
    assert list(timings.durations_ms) == ["search", "check"]


@pytest.mark.anyio
async def test_find_alternatives_never_offers_the_wrong_kind_of_product(monkeypatch: pytest.MonkeyPatch) -> None:
    use_search(monkeypatch, FOUND)
    verdicts = judged(("R7600",), R7700="fits", I5="conflict", R7600="fits", R5600="conflict", CHEAP="fits")
    use_claude(monkeypatch, FakeClaude(candidate_verdicts=verdicts))

    result = await find_alternatives(AlternativesRequest(**CPU_PART, setup=[BOARD], product=I5))

    assert [a.product.asin for a in result.alternatives] == ["R7700", "CHEAP", "R5600"]


@pytest.mark.anyio
async def test_find_alternatives_leaves_out_options_that_only_tie(monkeypatch: pytest.MonkeyPatch) -> None:
    same = product("SAME", 200)  # a conflict and $20 over budget, like the product to beat
    use_search(monkeypatch, [same, R5600])
    verdicts = judged(SAME="conflict", R5600="conflict", I5="conflict")
    use_claude(monkeypatch, FakeClaude(candidate_verdicts=verdicts))

    result = await find_alternatives(AlternativesRequest(**CPU_PART, setup=[BOARD], product=I5))

    assert [(a.product.asin, a.score) for a in result.alternatives] == [("R5600", 60)]


@pytest.mark.anyio
async def test_find_alternatives_judges_each_candidate_and_the_product_to_beat_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_search(monkeypatch, FOUND)
    claude = use_claude(monkeypatch, FakeClaude(candidate_verdicts=ALL_JUDGED))

    await find_alternatives(AlternativesRequest(**CPU_PART, setup=[BOARD, RAM], product=I5))

    request_line, category_line, candidates_line, setup_line = claude.prompts[0].split("\n")
    assert (request_line, category_line) == (f"Request: {REQUEST}", "Category: CPU")
    candidates = json.loads(candidates_line.removeprefix("Candidates: "))
    assert [c["asin"] for c in candidates] == ["R7700", "R7600", "R5600", "CHEAP", "I5"]
    assert candidates[0] == {"asin": "R7700", "title": "Product R7700"}
    assert candidates[-1] == {"asin": "I5", "title": "Product I5", "details": "Socket LGA 1700."}
    assert [p["category"] for p in json.loads(setup_line.removeprefix("Setup: "))] == ["Motherboard", "RAM"]
    assert claude.efforts == [agent.PICK_EFFORT]


@pytest.mark.anyio
async def test_find_alternatives_drops_candidates_claude_left_out(monkeypatch: pytest.MonkeyPatch) -> None:
    use_search(monkeypatch, FOUND)
    use_claude(monkeypatch, FakeClaude(candidate_verdicts=judged(R7700="fits", I5="conflict", R5600="conflict")))

    result = await find_alternatives(AlternativesRequest(**CPU_PART, setup=[BOARD], product=I5))

    assert [a.product.asin for a in result.alternatives] == ["R7700", "R5600"]


@pytest.mark.anyio
async def test_find_alternatives_raises_the_bar_when_claude_leaves_out_the_product_to_beat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_search(monkeypatch, FOUND)
    verdicts = judged(R7700="fits", R7600="fits", R5600="conflict", CHEAP="fits")
    use_claude(monkeypatch, FakeClaude(candidate_verdicts=verdicts))

    result = await find_alternatives(AlternativesRequest(**CPU_PART, setup=[BOARD], product=I5))

    # Without its conflict, the product to beat scores 90 for its price alone
    assert [(a.product.asin, a.score) for a in result.alternatives] == [("R7600", 100), ("R7700", 100)]


@pytest.mark.anyio
async def test_find_alternatives_without_a_product_returns_the_best_options(monkeypatch: pytest.MonkeyPatch) -> None:
    use_search(monkeypatch, FOUND)
    use_claude(monkeypatch, FakeClaude(candidate_verdicts=ALL_JUDGED))

    result = await find_alternatives(AlternativesRequest(**CPU_PART, setup=[BOARD]))

    assert [(a.product.asin, a.score, a.price_difference) for a in result.alternatives] == [
        ("R7600", 100, None),
        ("R7700", 100, None),
        ("CHEAP", 85, None),
    ]


@pytest.mark.anyio
async def test_find_alternatives_with_an_empty_setup_still_judges_the_match(monkeypatch: pytest.MonkeyPatch) -> None:
    use_search(monkeypatch, FOUND)
    verdicts = CandidateVerdicts(candidates=[CandidateVerdict(asin=p.asin, match=match(), checks=[]) for p in FOUND])
    claude = use_claude(monkeypatch, FakeClaude(candidate_verdicts=verdicts))

    result = await find_alternatives(AlternativesRequest(**CPU_PART, product=I5))

    # Match, price and reviews only: the product to beat is 90 for being over budget
    assert claude.prompts[0].endswith("Setup: []")
    assert [(a.product.asin, a.score) for a in result.alternatives] == [("R5600", 100), ("R7600", 100), ("R7700", 100)]
    assert [c.kind for c in result.alternatives[0].checks] == ["match", "budget", "reviews"]


@pytest.mark.anyio
async def test_find_alternatives_when_the_search_only_finds_the_product_to_beat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_search(monkeypatch, [I5])
    claude = use_claude(monkeypatch, FakeClaude())

    result = await find_alternatives(AlternativesRequest(**CPU_PART, setup=[BOARD], product=I5))

    assert result.alternatives == []
    assert claude.prompts == []


@pytest.mark.anyio
async def test_find_alternatives_raises_when_the_search_finds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    use_search(monkeypatch, [])
    claude = use_claude(monkeypatch, FakeClaude())

    with pytest.raises(SearchFailed):
        await find_alternatives(AlternativesRequest(**CPU_PART, setup=[BOARD], product=I5))
    assert claude.prompts == []
