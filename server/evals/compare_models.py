"""Compare Grok models on the planning and picking stages using saved Amazon candidates.

Spends xAI credit only (no Apify). From server/:
    uv run python -m evals.compare_models [--models grok-4.7 grok-4.3 ...] [--stage plan|pick]
"""

import argparse
import asyncio
import json
import math
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

import httpx
from pydantic import BaseModel

from evals.run_eval import PC_PARTS, RESULTS_DIR, find_part, matching_spec, ram_types_in, sockets_in
from server.agent import MAX_ITEMS, PICK_PROMPT, PLAN_PROMPT, get_client, pick_request
from server.config import get_settings
from server.models import BuildPart, BuildPicks, BuildPlan, Product

FIXTURES = Path("evals/fixtures/candidates.json")
DEFAULT_MODELS = ["grok-4.7", "grok-4.20-0309-reasoning", "grok-4.20-0309-non-reasoning", "grok-4.3"]
CASES_AT_ONCE = 2  # each case runs every model at the same time, so models share conditions


@dataclass
class Trial:
    stage: str
    model: str
    case: str
    seconds: float
    cost_usd: float = 0.0
    error: str = ""
    scores: dict[str, bool | None] = field(default_factory=dict)
    notes: str = ""


async def model_prices() -> dict[str, tuple[float, float]]:
    """USD per token (input, output) for each model, from xAI's model list."""
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            "https://api.x.ai/v1/language-models",
            headers={"Authorization": f"Bearer {get_settings().xai_api_key}"},
        )
    # Listed in ten-thousandths of a dollar per million tokens (20000 = $2.00 per million)
    return {
        m["id"]: (m["prompt_text_token_price"] / 1e10, m["completion_text_token_price"] / 1e10)
        for m in response.json()["models"]
    }


async def timed_parse[T: BaseModel](
    model: str, system: str, user: str, schema: type[T], prices: dict[str, tuple[float, float]]
) -> tuple[T | None, float, float]:
    start = time.perf_counter()
    completion = await get_client().chat.completions.parse(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format=schema,
    )
    seconds = time.perf_counter() - start
    usage = completion.usage
    price_in, price_out = prices.get(model, (0.0, 0.0))
    cost = (usage.prompt_tokens * price_in + usage.completion_tokens * price_out) if usage else 0.0
    return completion.choices[0].message.parsed, seconds, cost


def score_plan(build: dict[str, Any], plan: BuildPlan) -> tuple[dict[str, bool | None], str]:
    categories = [p.category for p in plan.parts]
    scores: dict[str, bool | None] = {
        "not rejected": plan.rejection is None,
        "budget read": math.isclose(plan.budget, build["budget"], rel_tol=0.01),
        "plan within budget": sum(p.max_price for p in plan.parts) <= plan.budget * 1.01,
        f"<= {MAX_ITEMS} items": 0 < len(plan.parts) <= MAX_ITEMS,
    }
    if build["kind"] == "pc":
        scores["all PC parts"] = all(
            any(k in c.lower() for c in categories for k in keywords) for keywords in PC_PARTS.values()
        )
    return scores, f"{len(categories)} items: {', '.join(categories)}"


def score_pick(build: dict[str, Any], picks: BuildPicks) -> tuple[dict[str, bool | None], str]:
    candidates = {cat: [Product(**p) for p in ps] for cat, ps in build["candidates"].items()}
    products = {p.asin: (cat, p) for cat, ps in candidates.items() for p in ps}
    valid = [pick for pick in picks.picks if pick.asin in products]
    # Score with the search query as category, so the PC part keywords match reliably
    parts = [BuildPart(category=products[p.asin][0], product=products[p.asin][1], reason=p.reason) for p in valid]
    total = sum(part.product.price for part in parts)
    covered = {part.category for part in parts}
    searchable = [cat for cat, ps in candidates.items() if ps]
    scores: dict[str, bool | None] = {
        "no made-up ASINs": len(valid) == len(picks.picks),
        "every item covered": set(searchable) <= covered,
        "one per item": len(covered) == len(parts),
        "within budget": total <= build["budget"],
        "uses >=50% budget": total >= 0.5 * build["budget"],
        "says compatible": picks.compatibility.compatible,
    }
    if build["kind"] == "pc":
        cpu, board, ram = (find_part(parts, name) for name in ("CPU", "Motherboard", "RAM"))
        scores["socket match"] = matching_spec("socket", cpu, board, sockets_in).passed
        scores["RAM type match"] = matching_spec("ram", ram, board, ram_types_in).passed
    return scores, f"${total:.2f} of ${build['budget']:g}, {len(covered)}/{len(searchable)} items"


async def run_trial(
    stage: str, model: str, build: dict[str, Any], prices: dict[str, tuple[float, float]]
) -> Trial:
    trial = Trial(stage, model, build["case"], 0.0)
    try:
        if stage == "plan":
            plan, trial.seconds, trial.cost_usd = await timed_parse(
                model, PLAN_PROMPT, build["request"], BuildPlan, prices
            )
            if plan is not None:
                trial.scores, trial.notes = score_plan(build, plan)
        else:
            candidates = {cat: [Product(**p) for p in ps] for cat, ps in build["candidates"].items()}
            user = pick_request(build["request"], build["budget"], candidates)
            picks, trial.seconds, trial.cost_usd = await timed_parse(model, PICK_PROMPT, user, BuildPicks, prices)
            if picks is not None:
                trial.scores, trial.notes = score_pick(build, picks)
        if not trial.scores:
            trial.error = "response did not match the schema"
    except Exception as e:  # report every failure as a result instead of stopping the comparison
        trial.error = f"{type(e).__name__}: {e}"[:200]
    return trial


def print_stage(stage: str, trials: list[Trial], models: list[str]) -> None:
    score_names = list(dict.fromkeys(name for t in trials for name in t.scores))
    print(f"\n=== {stage.upper()} stage ({len({t.case for t in trials})} cases per model)")
    header = f"{'MODEL':<30} {'p50':>6} {'max':>6} {'$/call':>8} {'errors':>6}  " + "  ".join(score_names)
    print(header)
    for model in models:
        mine = [t for t in trials if t.model == model]
        ok = [t for t in mine if not t.error]
        times = sorted(t.seconds for t in ok)
        p50 = times[len(times) // 2] if times else float("nan")
        cells = []
        for name in score_names:
            values = [t.scores.get(name) for t in ok if name in t.scores]
            passed = sum(v is True for v in values)
            unverified = sum(v is None for v in values)
            cells.append(f"{passed}/{len(values)}" + (f" ({unverified}?)" if unverified else "") if values else "-")
        cost = mean(t.cost_usd for t in ok) if ok else 0.0
        print(
            f"{model:<30} {p50:>5.1f}s {max(times, default=float('nan')):>5.1f}s ${cost:>7.4f} "
            f"{len(mine) - len(ok):>6}  " + "  ".join(f"{c:>{len(n)}}" for c, n in zip(cells, score_names))
        )
    for t in trials:
        if t.error:
            print(f"  error: {t.model} on {t.case}: {t.error}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--stage", choices=["plan", "pick"], help="run only one stage")
    args = parser.parse_args()

    builds = json.loads(FIXTURES.read_text())["builds"]
    prices = await model_prices()
    stages = [args.stage] if args.stage else ["plan", "pick"]
    limit = asyncio.Semaphore(CASES_AT_ONCE)

    async def run_case(stage: str, build: dict[str, Any]) -> list[Trial]:
        async with limit:
            return list(await asyncio.gather(*(run_trial(stage, m, build, prices) for m in args.models)))

    all_trials: list[Trial] = []
    for stage in stages:
        per_case = await asyncio.gather(*(run_case(stage, build) for build in builds))
        trials = [t for case_trials in per_case for t in case_trials]
        all_trials += trials
        print_stage(stage, trials, args.models)

    print(f"\nTotal xAI cost: ${sum(t.cost_usd for t in all_trials):.2f}")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"models-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps([asdict(t) for t in all_trials], indent=2))
    print(f"Full results: {path}")


if __name__ == "__main__":
    asyncio.run(main())
