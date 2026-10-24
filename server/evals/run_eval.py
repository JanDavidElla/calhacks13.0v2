"""Live evaluation of the running API. Spends real Apify and xAI credit.

Start the server first (uv run server), then from server/:
    uv run python -m evals.run_eval [--concurrency 3] [--only NAME] [--yes]
"""

import argparse
import asyncio
import json
import math
import re
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from evals.cases import AUDIO_DIR, TEXT_CASES, VOICE_CASES, Case
from server.config import get_settings
from server.models import BuildPart, BuildResponse
from server.stt import transcribe

RESULTS_DIR = Path("evals/results")
APIFY_COST_PER_BUILD = 0.18
MAX_WORD_ERROR_RATE = 0.15
MIN_BUDGET_USE = 0.5

# Keywords that identify each core PC part in a response's category names
PC_PARTS = {
    "CPU": ("cpu", "processor"),
    "Motherboard": ("motherboard",),
    "RAM": ("ram", "memory"),
    "Storage": ("storage", "ssd", "drive"),
    "Graphics card": ("graphics", "gpu", "video card"),
    "Power supply": ("power", "psu"),
    "Case": ("case",),
}
SOCKETS = ("AM4", "AM5", "LGA1200", "LGA1700", "LGA1851")
NUMBER_WORDS = (
    r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
    r"fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|"
    r"ninety|hundred|thousand)"
)


@dataclass
class Check:
    name: str
    passed: bool | None  # None: the listings don't say enough to verify
    detail: str = ""


@dataclass
class Result:
    case: str
    kind: str
    input: str
    status: int | None
    seconds: float
    stages_ms: dict[str, float] = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)
    detail: str = ""

    @property
    def passed(self) -> bool:
        return all(check.passed is not False for check in self.checks)


# Transcript checks


def words(text: str) -> list[str]:
    """Lowercase words with amounts removed; the budget check compares amounts separately."""
    text = text.lower()
    text = re.sub(rf"\b{NUMBER_WORDS}(?:[\s-]+(?:and\s+)?{NUMBER_WORDS})*\b", " ", text)
    text = re.sub(r"\$?\d[\d,.]*|\bdollars?\b", " ", text)
    return re.findall(r"[a-z']+", text)


def word_error_rate(expected: str, heard: str) -> float:
    ref, hyp = words(expected), words(heard)
    distances = list(range(len(hyp) + 1))
    for i, ref_word in enumerate(ref, 1):
        previous, distances[0] = distances[0], i
        for j, hyp_word in enumerate(hyp, 1):
            previous, distances[j] = distances[j], min(
                distances[j] + 1, distances[j - 1] + 1, previous + (ref_word != hyp_word)
            )
    return distances[-1] / max(len(ref), 1)


def transcript_checks(case: Case, transcript: str) -> list[Check]:
    wer = word_error_rate(case.request, transcript)
    checks = [Check("words heard", wer <= MAX_WORD_ERROR_RATE, f"WER {wer:.0%}: {transcript!r}")]
    if case.budget is not None:
        amounts = [float(a.replace(",", "")) for a in re.findall(r"\d[\d,]*(?:\.\d+)?", transcript)]
        checks.append(Check("budget heard", case.budget in amounts, f"amounts {amounts}"))
    return checks


# Build checks


def find_part(parts: list[BuildPart], name: str) -> BuildPart | None:
    return next((p for p in parts if any(k in p.category.lower() for k in PC_PARTS[name])), None)


def tokens_in(title: str, options: tuple[str, ...]) -> set[str]:
    compact = title.upper().replace(" ", "")
    return {option for option in options if option in compact}


def sockets_in(title: str) -> set[str]:
    sockets = tokens_in(title, SOCKETS)
    # CPU titles often name the model rather than the socket
    upper = title.upper()
    if ryzen := re.search(r"RYZEN\s*[3579]\s*(\d)\d{3}", upper):
        sockets.add("AM4" if ryzen.group(1) in "12345" else "AM5")
    if re.search(r"\bI[3579]-1[234]\d{3}", upper):
        sockets.add("LGA1700")
    return sockets


def ram_types_in(title: str) -> set[str]:
    return tokens_in(title, ("DDR4", "DDR5"))


def matching_spec(
    name: str, a: BuildPart | None, b: BuildPart | None, specs_in: Callable[[str], set[str]]
) -> Check:
    """Independent check of Grok's compatibility claims, using only the listing titles."""
    if a is None or b is None:
        return Check(name, None, "part missing")
    a_specs, b_specs = specs_in(a.product.title), specs_in(b.product.title)
    if not a_specs or not b_specs:
        return Check(name, None, f"not in titles ({a_specs or '?'} vs {b_specs or '?'})")
    return Check(name, bool(a_specs & b_specs), f"{a_specs} vs {b_specs}")


def build_checks(case: Case, body: dict[str, Any]) -> list[Check]:
    try:
        build = BuildResponse.model_validate(body)
    except ValidationError as e:
        return [Check("response format", False, str(e).splitlines()[0])]

    assert case.budget is not None
    parts, asins = build.parts, [p.product.asin for p in build.parts]
    checks = [
        Check("response format", True),
        Check("budget read", math.isclose(build.budget, case.budget, rel_tol=0.01), f"${build.budget:g}"),
        Check("within budget", build.total <= build.budget, f"${build.total:g} of ${build.budget:g}"),
        Check("uses budget", build.total >= MIN_BUDGET_USE * build.budget, f"{build.total / build.budget:.0%}"),
        Check("has parts", bool(parts), f"{len(parts)} parts"),
        Check("no duplicates", len(set(asins)) == len(asins)),
        Check("amazon links", all(p.product.url == f"https://www.amazon.com/dp/{p.product.asin}" for p in parts)),
        Check("images", all(p.product.image for p in parts),
              f"{sum(bool(p.product.image) for p in parts)}/{len(parts)}"),
        Check("compatible", build.compatibility.compatible,
              "; ".join(c.reason for c in build.compatibility.checks if not c.compatible)),
    ]
    if case.kind == "pc":
        missing = [name for name in PC_PARTS if find_part(parts, name) is None]
        checks += [
            Check("all PC parts", not missing, f"missing {missing}" if missing else ""),
            Check("compatibility explained", len(build.compatibility.checks) >= 3,
                  f"{len(build.compatibility.checks)} checks"),
            matching_spec("socket match", find_part(parts, "CPU"), find_part(parts, "Motherboard"), sockets_in),
            matching_spec("RAM type match", find_part(parts, "RAM"), find_part(parts, "Motherboard"), ram_types_in),
        ]
    return checks


# Running cases


def expected_statuses(case: Case) -> set[int]:
    return {"pc": {200}, "general": {200}, "reject": {400}, "bad_audio": {400}}[case.kind]


def parse_server_timing(header: str) -> dict[str, float]:
    stages = re.findall(r"([\w-]+);dur=([\d.]+)", header)
    return {name: float(ms) for name, ms in stages}


async def run_api_case(client: httpx.AsyncClient, case: Case, limit: asyncio.Semaphore) -> Result:
    if case.audio:
        audio_path = Path(AUDIO_DIR) / case.audio
        request: dict[str, Any] = {"files": {"audio": (case.audio, audio_path.read_bytes())}}
    else:
        request = {"data": {"text": case.request}}

    async with limit:
        start = time.perf_counter()
        try:
            response = await client.post("/api/build", **request)
        except httpx.HTTPError as e:
            seconds = time.perf_counter() - start
            return Result(case.name, case.kind, input_type(case), None, seconds,
                          checks=[Check("expected status", False, f"request failed: {e!r}")])
        seconds = time.perf_counter() - start

    body = response.json()
    status_ok = response.status_code in expected_statuses(case)
    result = Result(
        case.name, case.kind, input_type(case), response.status_code, seconds,
        stages_ms=parse_server_timing(response.headers.get("server-timing", "")),
        checks=[Check("expected status", status_ok, f"got {response.status_code}")],
        detail=body.get("detail") or body.get("summary", ""),
    )
    if response.status_code == 200:
        result.checks += build_checks(case, body)
        if case.audio:
            result.checks += transcript_checks(case, body["transcript"])
    elif case.kind in ("reject", "bad_audio"):
        result.checks.append(Check("explains why", bool(body.get("detail")), body.get("detail", "")))
    return result


async def run_transcribe_case(case: Case) -> Result:
    assert case.audio
    audio = (Path(AUDIO_DIR) / case.audio).read_bytes()
    start = time.perf_counter()
    transcript = await transcribe(audio, case.audio)
    seconds = time.perf_counter() - start
    return Result(case.name, case.kind, "voice (stt only)", 200, seconds, {"stt": seconds * 1000},
                  transcript_checks(case, transcript), transcript)


def input_type(case: Case) -> str:
    return "voice" if case.audio else "text"


async def apify_usage_usd() -> float:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            "https://api.apify.com/v2/users/me/limits",
            headers={"Authorization": f"Bearer {get_settings().apify_api_token}"},
        )
    return response.json()["data"]["current"]["monthlyUsageUsd"]


# Report


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(pct / 100 * len(ordered)) - 1)]


def print_report(results: list[Result], wall_seconds: float, concurrency: int, apify_spent: float) -> dict[str, Any]:
    print(f"\n{'CASE':<24} {'INPUT':<16} {'HTTP':>4} {'TIME':>6}  RESULT")
    for r in results:
        failed = [f"{c.name} ({c.detail})" if c.detail else c.name for c in r.checks if c.passed is False]
        unverified = [c.name for c in r.checks if c.passed is None]
        verdict = "PASS" if r.passed else "FAIL: " + "; ".join(failed)
        if unverified:
            verdict += f"  [unverified: {', '.join(unverified)}]"
        print(f"{r.case:<24} {r.input:<16} {r.status or '-':>4} {r.seconds:>5.1f}s  {verdict}")

    builds = [r for r in results if r.status == 200 and r.kind in ("pc", "general") and "stt only" not in r.input]
    stages = ["stt", "plan", "search", "pick", "total"]
    print(f"\nLATENCY (successful API builds: {len(builds)}; stt also includes transcription-only cases)")
    print(f"{'STAGE':<8} {'p50':>8} {'p95':>8} {'n':>3}")
    latency: dict[str, dict[str, float]] = {}
    for stage in stages:
        source = results if stage == "stt" else builds
        values = [r.stages_ms[stage] / 1000 for r in source if stage in r.stages_ms]
        if values:
            latency[stage] = {"p50": percentile(values, 50), "p95": percentile(values, 95), "n": len(values)}
            print(f"{stage:<8} {latency[stage]['p50']:>7.1f}s {latency[stage]['p95']:>7.1f}s {len(values):>3}")

    api_results = [r for r in results if "stt only" not in r.input]
    unexpected = [r for r in api_results if not r.checks or r.checks[0].passed is False]
    server_errors = [r for r in api_results if r.status is None or r.status >= 500]
    summary = {
        "cases": len(results),
        "passed": sum(r.passed for r in results),
        "error_rate": len(unexpected) / max(len(api_results), 1),
        "server_errors": len(server_errors),
        "concurrency": concurrency,
        "wall_seconds": wall_seconds,
        "builds_per_minute": len(builds) / (wall_seconds / 60),
        "apify_spent_usd": apify_spent,
        "latency_s": latency,
    }
    print(
        f"\nSUMMARY  {summary['passed']}/{summary['cases']} cases passed | "
        f"error rate {summary['error_rate']:.0%} (unexpected HTTP status) | "
        f"server errors {summary['server_errors']}\n"
        f"         throughput {summary['builds_per_minute']:.1f} builds/min at concurrency {concurrency} "
        f"({len(builds)} builds in {wall_seconds:.0f}s) | Apify spent ${apify_spent:.2f}"
    )
    return summary


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--concurrency", type=int, default=3, help="API requests in flight at once")
    parser.add_argument("--only", help="run only cases whose name contains this text")
    parser.add_argument("--yes", action="store_true", help="skip the cost confirmation")
    args = parser.parse_args()

    cases = [c for c in TEXT_CASES + VOICE_CASES if not args.only or args.only in c.name]
    api_cases = [c for c in cases if not c.transcribe_only]
    stt_cases = [c for c in cases if c.transcribe_only]
    builds = sum(c.kind in ("pc", "general") for c in api_cases)

    async with httpx.AsyncClient(base_url=args.url, timeout=300) as client:
        try:
            (await client.get("/api/health")).raise_for_status()
        except httpx.HTTPError:
            sys.exit(f"No server at {args.url}. Start it first: uv run server")

        print(f"{len(api_cases)} API cases ({builds} full builds), {len(stt_cases)} transcription-only cases")
        print(f"Estimated cost: ~${builds * APIFY_COST_PER_BUILD:.2f} Apify + a few cents of xAI")
        if not args.yes and input("Continue? [y/N] ").lower() != "y":
            return

        usage_before = await apify_usage_usd()
        limit = asyncio.Semaphore(args.concurrency)
        start = time.perf_counter()
        results = await asyncio.gather(
            *(run_api_case(client, case, limit) for case in api_cases),
            *(run_transcribe_case(case) for case in stt_cases),
        )
        wall_seconds = time.perf_counter() - start
        apify_spent = await apify_usage_usd() - usage_before

    summary = print_report(list(results), wall_seconds, args.concurrency, apify_spent)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps({"summary": summary, "results": [asdict(r) for r in results]}, indent=2))
    print(f"Full results: {path}")


if __name__ == "__main__":
    asyncio.run(main())
