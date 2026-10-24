import json

from openai import AsyncOpenAI
from pydantic import BaseModel

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

# Per stage so each can use the model that tests best for it (see evals/compare_models.py).
# Picked 2026-10-24: planning needs no reasoning (equal quality, ~6x faster than grok-4.7);
# picking needs it to choose good-value parts, and 4.20 reasoning matched grok-4.7 at ~2.5x the speed.
PLAN_MODEL = "grok-4.20-0309-non-reasoning"
PICK_MODEL = "grok-4.20-0309-reasoning"
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


def get_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=get_settings().xai_api_key, base_url="https://api.x.ai/v1")


async def ask_grok[T: BaseModel](
    client: AsyncOpenAI, model: str, system: str, user: str, schema: type[T]
) -> T:
    completion = await client.chat.completions.parse(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format=schema,
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise RuntimeError("Grok did not return a valid response")
    return parsed


def pick_request(request: str, budget: float, candidates: dict[str, list[Product]]) -> str:
    """The picking message for Grok; links and images are left out to save tokens."""
    candidates_json = json.dumps(
        {category: [p.model_dump(exclude={"url", "image"}) for p in products]
         for category, products in candidates.items()}
    )
    return f"Request: {request}\nBudget: ${budget}\nCandidates: {candidates_json}"


async def build(request: str, timings: Timings | None = None) -> BuildResponse:
    """Plan a shopping list for the request, search Amazon, and pick products."""
    timings = timings or Timings()
    client = get_client()
    with timings.measure("plan"):
        plan = await ask_grok(client, PLAN_MODEL, PLAN_PROMPT, request, BuildPlan)
    if plan.rejection:
        raise BuildRejected(plan.rejection)
    with timings.measure("search"):
        candidates = await search_parts(plan.parts[:MAX_ITEMS])
    with timings.measure("pick"):
        picks = await ask_grok(
            client, PICK_MODEL, PICK_PROMPT, pick_request(request, plan.budget, candidates), BuildPicks
        )

    # Look picks up by ASIN so prices and links come from Amazon, not from Grok
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
        return await ask_grok(
            get_client(), PICK_MODEL, CHECK_PROMPT, f"Products: {listing}", Compatibility
        )
