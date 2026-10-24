import json
from typing import Literal

from anthropic import AsyncAnthropic
from pydantic import BaseModel, ValidationError

from server.amazon import search_parts, search_url
from server.config import get_settings
from server.models import (
    Alternative,
    AlternativesRequest,
    AlternativesResponse,
    BuildPart,
    BuildPicks,
    BuildPlan,
    BuildResponse,
    CandidateVerdicts,
    Compatibility,
    EvaluateRequest,
    Evaluation,
    FitCheck,
    PartChoice,
    PlannedPart,
    PlanResponse,
    Product,
    Verdict,
)
from server.score import score_product
from server.timing import Timings

type Effort = Literal["low", "medium", "high", "xhigh", "max"]

MODEL = "claude-opus-5-5"
# Effort trades speed for reasoning, per stage: planning is a simple list, while picking
# and checking need reasoning to choose good-value parts that work together
PLAN_EFFORT: Effort = "low"
PICK_EFFORT: Effort = "medium"
# Each item is one Amazon search, so this also caps Apify cost per request
MAX_ITEMS = 8
MAX_ALTERNATIVES = 3
# A stalled request fails after this long instead of the SDK's default 10 minutes; a whole
# build, with several Claude calls, takes about 40s
CLAUDE_TIMEOUT_S = 60

PLAN_PROMPT = f"""You are a shopping assistant that plans what to buy on Amazon.
Turn the user's request into a list of up to {MAX_ITEMS} distinct items.
- Builds and setups (a PC, a home office, a streaming kit): list every item
  needed for it to work, e.g. a PC needs CPU, motherboard, RAM, storage,
  graphics card, power supply and case.
- Themes and open-ended requests (Christmas, filling a room with nature items,
  gifts for a hobby): pick a varied set of items that fit the theme well,
  rather than several of the same thing.
Split the total budget across the items so the sum stays within it. If no
budget is given, choose a typical one for the request and set
budget_estimated. Write short, specific Amazon search queries that will find
the main product, not accessories.
Set rejection to a short explanation, and leave parts empty, only if the
request can't be met by buying products or the budget clearly can't cover it
(e.g. a gaming PC for $50). If you can't tell what kind of items to buy (e.g.
"stuff for my house"), or the request needs far more than {MAX_ITEMS} items to
be useful, set rejection to one short question that would narrow it instead.
Themes, such as Christmas decor for an apartment, are not too broad."""

COMPATIBILITY_GUIDE = """Explain compatibility with one check per relationship that
matters. For PCs: CPU socket vs motherboard, RAM type vs motherboard, power
supply wattage vs CPU and graphics card, and motherboard size vs case. For other
setups, cover whatever must fit together (connectors, sizes, platforms), or
return no checks if nothing depends on anything else. Use the product titles
and well-known specs of the named models (e.g. a graphics card's typical power
draw). Mark a check incompatible only for a definite conflict, and say so in the
reason when neither confirms a detail."""

PICK_PROMPT = f"""You choose one Amazon product per item for the user's request.
Pick only from the candidates provided, copying the ASIN exactly. Skip
candidates that don't match the item, make sure products work together and suit
the request's theme, and keep the total price within the budget. Prefer
well-reviewed products.
{COMPATIBILITY_GUIDE}"""

CHECK_PROMPT = f"""You check whether a set of products works together.
{COMPATIBILITY_GUIDE}"""

FIT_GUIDE = """Write one check per relationship that matters between the product
and the setup. For PCs: CPU socket vs motherboard, RAM type vs motherboard, power
supply wattage vs CPU and graphics card, and motherboard size vs case. For other
setups, cover whatever must fit together (connectors, mounts, sizes, platforms),
or return no checks if nothing in the setup depends on the product (decor,
gifts). Compare the product with the setup only, never two setup items with each
other, and include the product's category in every check's parts, copying
categories exactly. Use the listings' titles and details and the well-known specs
of the named models (e.g. a graphics card's typical power draw). Choose conflict
only for a definite conflict, and unconfirmed when neither the listings nor the
model's known specs settle a detail that matters."""

MATCH_GUIDE = """First judge the match: the product must be the kind of product
the part calls for, not an accessory or a different item, and meet every need
the request states that applies to this part (e.g. quiet, white, fits a small
room). Choose unconfirmed when the listing doesn't show a stated need, and
mismatch for the wrong kind of product or a need it clearly misses. Needs the
request doesn't state don't count. Leave price and ratings out: they're scored
separately."""

EVALUATE_PROMPT = f"""You judge a product the user is viewing on Amazon for one
part of their request.
{MATCH_GUIDE}
Then check whether it works with the products already in their setup.
{FIT_GUIDE}"""

ALTERNATIVES_PROMPT = f"""You judge several candidate products for one part of
the user's request. Return one entry for every candidate, copying its ASIN
exactly, and judge each candidate as the product on its own.
{MATCH_GUIDE}
Then check whether it works with the products already in the user's setup.
{FIT_GUIDE}"""


class BuildRejected(Exception):
    """The request isn't a shopping request or its budget can't cover it."""


class SearchFailed(Exception):
    """Amazon returned no results for a part, even after retries."""


class InvalidResponse(RuntimeError):
    """Claude's reply didn't match the schema, or every model declined the request."""


def get_client() -> AsyncAnthropic:
    return AsyncAnthropic(api_key=get_settings().anthropic_api_key, timeout=CLAUDE_TIMEOUT_S)


async def ask_claude[T: BaseModel](
    client: AsyncAnthropic, effort: Effort, system: str, user: str, schema: type[T]
) -> T:
    try:
        message = await client.beta.messages.parse(
            model=MODEL,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema,
            output_config={"effort": effort},
            # If Claude declines a request, the API retries it on a fallback model in the same call
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except ValidationError as e:
        # parse validates the text as it arrives, so a reply that isn't the schema raises here
        raise InvalidResponse("Claude did not return a valid response") from e
    parsed = message.parsed_output
    if parsed is None:
        raise InvalidResponse("Claude did not return a valid response")
    return parsed


def pick_request(request: str, budget: float, candidates: dict[str, list[Product]]) -> str:
    """The picking message for Claude; links and images are left out to save tokens."""
    candidates_json = json.dumps(
        {category: [p.model_dump(exclude={"url", "image", "details"}) for p in products]
         for category, products in candidates.items()}
    )
    return f"Request: {request}\nBudget: ${budget}\nCandidates: {candidates_json}"


async def make_plan(client: AsyncAnthropic, request: str) -> BuildPlan:
    """Turn the request into a shopping list of at most MAX_ITEMS items."""
    plan = await ask_claude(client, PLAN_EFFORT, PLAN_PROMPT, request, BuildPlan)
    if plan.rejection:
        raise BuildRejected(plan.rejection)
    return plan.model_copy(update={"parts": plan.parts[:MAX_ITEMS]})


async def plan_checklist(request: str, timings: Timings | None = None) -> PlanResponse:
    """Turn the request into the Evaluate flow's checklist, with an Amazon search link per part."""
    timings = timings or Timings()
    with timings.measure("plan"):
        plan = await make_plan(get_client(), request)
    return PlanResponse(
        transcript=request,
        budget=plan.budget,
        budget_estimated=plan.budget_estimated,
        parts=[
            PlannedPart(**part.model_dump(), search_url=search_url(part.search_query, part.max_price))
            for part in plan.parts
        ],
    )


async def build(request: str, timings: Timings | None = None) -> BuildResponse:
    """Plan a shopping list for the request, search Amazon, and pick products."""
    timings = timings or Timings()
    client = get_client()
    with timings.measure("plan"):
        plan = await make_plan(client, request)
    with timings.measure("search"):
        candidates = await search_parts(plan.parts)
    with timings.measure("pick"):
        picks = await ask_claude(
            client, PICK_EFFORT, PICK_PROMPT, pick_request(request, plan.budget, candidates), BuildPicks
        )

    # Look picks up by ASIN so prices and links come from Amazon, not from Claude
    products: dict[str, Product] = {p.asin: p for ps in candidates.values() for p in ps}
    parts = [
        BuildPart(category=pick.category, product=products[pick.asin], reason=pick.reason)
        for pick in picks.picks
        if pick.asin in products
    ]
    return BuildResponse(
        transcript=request,
        budget=plan.budget,
        total=round(sum(part.product.price for part in parts), 2),
        summary=picks.summary,
        parts=parts,
        compatibility=picks.compatibility,
    )


async def check_compatibility(parts: list[PartChoice], timings: Timings | None = None) -> Compatibility:
    """Explain whether the given products work together, e.g. after the user swaps a part."""
    timings = timings or Timings()
    listing = json.dumps([{"category": p.category, "title": p.product.title} for p in parts])
    with timings.measure("check"):
        return await ask_claude(
            get_client(), PICK_EFFORT, CHECK_PROMPT, f"Products: {listing}", Compatibility
        )


def listing(category: str, product: Product) -> dict[str, str]:
    """A product as Claude sees it to judge fit: prices and ratings are scored in code instead."""
    return {"category": category, **product.model_dump(include={"title", "details"}, exclude_none=True)}


def setup_listing(setup: list[PartChoice]) -> str:
    return json.dumps([listing(part.category, part.product) for part in setup])


def other_parts(category: str, setup: list[PartChoice]) -> list[PartChoice]:
    # A setup item in the product's own category is the one the product would replace
    return [part for part in setup if part.category != category]


def checks_on(category: str, fits: list[FitCheck]) -> list[FitCheck]:
    # Claude is told not to, but a check between two setup items says nothing about this product
    return [fit for fit in fits if category in fit.parts]


def request_line(request: str | None) -> str:
    return f"Request: {request}\n" if request else ""


async def evaluate(request: EvaluateRequest, timings: Timings | None = None) -> Evaluation:
    """Score one product for its part of the request and against the user's setup."""
    timings = timings or Timings()
    product = json.dumps(listing(request.category, request.product))
    setup = other_parts(request.category, request.setup)
    with timings.measure("check"):
        verdict = await ask_claude(
            get_client(), PICK_EFFORT, EVALUATE_PROMPT,
            f"{request_line(request.request)}Product: {product}\nSetup: {setup_listing(setup)}", Verdict,
        )
    return score_product(
        request.category, request.product, verdict.match, checks_on(request.category, verdict.checks),
        request.max_price,
    )


async def find_alternatives(request: AlternativesRequest, timings: Timings | None = None) -> AlternativesResponse:
    """Search Amazon for the part and return the options that score highest for it.

    With a product to beat, only options that score higher than it come back.
    """
    timings = timings or Timings()
    with timings.measure("search"):
        found = (await search_parts([request]))[request.category]
    if not found:
        raise SearchFailed("Amazon search found no results for this part. Try again.")
    beat = request.product
    # Keyed by ASIN, which also drops repeated results and the product to beat
    candidates = {p.asin: p for p in found if beat is None or p.asin != beat.asin}
    if not candidates:
        return AlternativesResponse(alternatives=[])

    # The product to beat is judged in the same call, so it's held to the same standard
    judged = [*candidates.values(), *([beat] if beat else [])]
    listings = [p.model_dump(include={"asin", "title", "details"}, exclude_none=True) for p in judged]
    setup = other_parts(request.category, request.setup)
    with timings.measure("check"):
        result = await ask_claude(
            get_client(), PICK_EFFORT, ALTERNATIVES_PROMPT,
            f"{request_line(request.request)}Category: {request.category}\n"
            f"Candidates: {json.dumps(listings)}\nSetup: {setup_listing(setup)}",
            CandidateVerdicts,
        )
    verdicts = {v.asin: v for v in result.candidates}

    def score(product: Product) -> Evaluation:
        verdict = verdicts.get(product.asin)
        return score_product(
            request.category, product,
            verdict.match if verdict else None,
            checks_on(request.category, verdict.checks) if verdict else [],
            request.max_price,
        )

    # Candidates Claude left out aren't offered, since how they fit is unknown, and neither is
    # the wrong kind of product. If Claude left out the product to beat, it gets no match or
    # compatibility checks, which only raises the bar
    offered = [p for p in candidates.values() if p.asin in verdicts and verdicts[p.asin].match.result != "mismatch"]
    bar = score(beat).score if beat else None
    scored = [(product, score(product)) for product in offered]
    alternatives = [
        Alternative(
            product=product,
            score=evaluation.score,
            checks=evaluation.checks,
            price_difference=round(product.price - beat.price, 2) if beat else None,
        )
        for product, evaluation in scored
        if bar is None or evaluation.score > bar
    ]
    alternatives.sort(key=lambda a: (-a.score, a.product.price))
    return AlternativesResponse(alternatives=alternatives[:MAX_ALTERNATIVES])
