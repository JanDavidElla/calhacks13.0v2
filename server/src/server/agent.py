import json
from typing import Literal

from anthropic import AsyncAnthropic
from pydantic import BaseModel, ValidationError

from server.amazon import search_parts
from server.config import get_settings
from server.models import (
    BuildPart,
    BuildPicks,
    BuildPlan,
    BuildResponse,
    Compatibility,
    PartChoice,
    Product,
)
from server.timing import Timings

type Effort = Literal["low", "medium", "high", "xhigh", "max"]

MODEL = "claude-opus-5-5"
# Effort trades speed for reasoning, per stage: planning is a simple list, while picking
# and checking need reasoning to choose good-value parts that work together
PLAN_EFFORT: Effort = "low"
PICK_EFFORT: Effort = "medium"
# Each item is one Amazon search, so this also caps Apify cost per request
MAX_ITEMS = 8

PLAN_PROMPT = f"""You are a shopping assistant that plans what to buy on Amazon.
Turn the user's request into a list of up to {MAX_ITEMS} distinct items.
- Builds and setups (a PC, a home office, a streaming kit): list every item
  needed for it to work, e.g. a PC needs CPU, motherboard, RAM, storage,
  graphics card, power supply and case.
- Themes and open-ended requests (Christmas, filling a room with nature items,
  gifts for a hobby): pick a varied set of items that fit the theme well,
  rather than several of the same thing.
Split the total budget across the items so the sum stays within it. If no
budget is given, choose a sensible one. Write short, specific Amazon search
queries that will find the main product, not accessories.
Set rejection to a short explanation, and leave parts empty, only if the
request can't be met by buying products or the budget clearly can't cover it
(e.g. a gaming PC for $50)."""

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


class BuildRejected(Exception):
    """The request isn't a shopping request or its budget can't cover it."""


def get_client() -> AsyncAnthropic:
    return AsyncAnthropic(api_key=get_settings().anthropic_api_key)


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
        raise RuntimeError("Claude did not return a valid response") from e
    parsed = message.parsed_output
    if parsed is None:
        raise RuntimeError("Claude did not return a valid response")
    return parsed


def pick_request(request: str, budget: float, candidates: dict[str, list[Product]]) -> str:
    """The picking message for Claude; links and images are left out to save tokens."""
    candidates_json = json.dumps(
        {category: [p.model_dump(exclude={"url", "image", "details"}) for p in products]
         for category, products in candidates.items()}
    )
    return f"Request: {request}\nBudget: ${budget}\nCandidates: {candidates_json}"


async def build(request: str, timings: Timings | None = None) -> BuildResponse:
    """Plan a shopping list for the request, search Amazon, and pick products."""
    timings = timings or Timings()
    client = get_client()
    with timings.measure("plan"):
        plan = await ask_claude(client, PLAN_EFFORT, PLAN_PROMPT, request, BuildPlan)
    if plan.rejection:
        raise BuildRejected(plan.rejection)
    with timings.measure("search"):
        candidates = await search_parts(plan.parts[:MAX_ITEMS])
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
