"""A/B test the Amazon scraper's useCaptchaSolver option on identical searches.

Spends Apify credit (1 result per search keeps it cheap). From server/:
    uv run python -m evals.compare_captcha
"""

import asyncio
from typing import Any

from apify_client import ApifyClientAsync

from server.amazon import ACTOR_ID, search_url, to_product
from server.config import get_settings

# The first four came back empty during the 2026-10-24 live eval
SEARCHES = [
    ("AMD Ryzen 5 5500 CPU", 180),
    ("550W 80 Plus Bronze power supply", 90),
    ("himalayan pink salt lamp", 33),
    ("live boston fern houseplant", 33),
    ("B550 ATX motherboard", 140),
    ("16GB DDR4 3200MHz desktop RAM", 67),
    ("1TB NVMe SSD", 90),
    ("ATX mid tower PC case", 90),
    ("gaming headset with microphone", 135),
    ("wired gaming mouse", 90),
    ("ergonomic office desk chair", 150),
    ("small artificial Christmas tree 4 foot", 70),
    ("warm white Christmas string lights indoor", 30),
    ("Christmas wreath for front door", 40),
    ("assorted mini succulent plants", 30),
    ("preserved moss wall art frame", 30),
    ("polarized fishing sunglasses for men", 33),
    ("quick dry sand free beach towel", 22),
    ("stainless steel fishing pliers with sheath", 21),
    ("insulated stainless steel water bottle", 14),
]


async def run_arm(client: ApifyClientAsync, use_captcha_solver: bool) -> dict[str, Any]:
    urls = [search_url(query, price) for query, price in SEARCHES]
    run = await client.actor(ACTOR_ID).call(
        run_input={
            "categoryOrProductUrls": [{"url": url} for url in urls],
            "maxItemsPerStartUrl": 1,
            "scrapeProductDetails": False,
            "useCaptchaSolver": use_captcha_solver,
        },
        max_items=len(urls),
        logger=None,
    )
    assert run is not None
    items = (await client.dataset(run.default_dataset_id).list_items()).items
    found = {item["input"] for item in items if to_product(item)}
    log = (await client.log(run.id).get()) or ""
    return {
        "empty": [query for (query, _), url in zip(SEARCHES, urls) if url not in found],
        "seconds": (run.finished_at - run.started_at).total_seconds(),
        "cost_usd": run.usage_total_usd or 0.0,
        "captcha_log_lines": sum("captcha" in line.lower() for line in log.splitlines()),
        "timeouts": sum("timed out" in line for line in log.splitlines()),
    }


async def main() -> None:
    client = ApifyClientAsync(get_settings().apify_api_token)
    without, with_solver = await asyncio.gather(run_arm(client, False), run_arm(client, True))
    print(f"{'':<16} {'empty':>6} {'time':>6} {'cost':>7} {'timeouts':>8} {'captcha log lines':>18}")
    for name, arm in (("without solver", without), ("with solver", with_solver)):
        print(
            f"{name:<16} {len(arm['empty']):>3}/{len(SEARCHES)} {arm['seconds']:>5.0f}s ${arm['cost_usd']:>6.3f} "
            f"{arm['timeouts']:>8} {arm['captcha_log_lines']:>18}"
        )
        for query in arm["empty"]:
            print(f"    empty: {query}")


if __name__ == "__main__":
    asyncio.run(main())
