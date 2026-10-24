from collections import defaultdict
from typing import Any
from urllib.parse import urlencode

from apify_client import ApifyClientAsync

from server.config import get_settings
from server.models import PartPlan, Product

ACTOR_ID = "junglee/amazon-crawler"
RESULTS_PER_SEARCH = 5
# Search above each part's share so better options show up; Claude keeps the total in budget
PRICE_HEADROOM = 1.5
# Amazon randomly serves empty results pages to scrapers (10-37% of searches in testing),
# so empty searches are re-run; each retry only charges for the results it finds
MAX_RETRIES = 2
# The cap docs/api-contract.md sets for a product page's details
DETAILS_MAX_CHARS = 4000


def search_url(query: str, max_price: float) -> str:
    # p_36 is Amazon's price filter, in cents
    params = {"k": query, "rh": f"p_36:-{round(max_price * PRICE_HEADROOM * 100)}"}
    return f"https://www.amazon.com/s?{urlencode(params)}"


def details_text(item: dict[str, Any]) -> str | None:
    """The listing's bullet points and spec table, the text the extension reads from a product page."""
    bullets = item.get("features") or []
    specs = [f"{a['key']}: {a['value']}" for a in item.get("attributes") or [] if a.get("key") and a.get("value")]
    return "\n".join([*bullets, *specs])[:DETAILS_MAX_CHARS] or None


def to_product(item: dict[str, Any]) -> Product | None:
    """Convert an Apify item to a Product, skipping errors and unpriced listings."""
    price = (item.get("price") or {}).get("value")
    if item.get("error") or not item.get("asin") or price is None:
        return None
    return Product(
        asin=item["asin"],
        title=item["title"],
        price=price,
        url=f"https://www.amazon.com/dp/{item['asin']}",
        image=item.get("imageUrl"),
        stars=item.get("stars"),
        details=details_text(item),
    )


async def run_searches(client: ApifyClientAsync, urls: list[str], details: bool) -> dict[str, list[Product]]:
    """Run all search URLs in a single Actor run, keyed by URL."""
    # One run for all searches: the free plan's memory limit allows only ~4 runs at once
    run = await client.actor(ACTOR_ID).call(
        run_input={
            "categoryOrProductUrls": [{"url": url} for url in urls],
            "maxItemsPerStartUrl": RESULTS_PER_SEARCH,
            "scrapeProductDetails": details,
        },
        max_items=RESULTS_PER_SEARCH * len(urls),
        logger=None,
    )
    by_url: dict[str, list[Product]] = defaultdict(list)
    if run is None:
        return by_url
    page = await client.dataset(run.default_dataset_id).list_items()
    # Each item records the search URL it came from in "input"
    for item in page.items:
        if product := to_product(item):
            by_url[item.get("input", "")].append(product)
    return by_url


async def search_parts(parts: list[PartPlan], details: bool = False) -> dict[str, list[Product]]:
    """Search Amazon for every part, keyed by category.

    With details, each result also opens its product page for the bullet points and spec
    table, which adds about 4 seconds.
    """
    urls = {part.category: search_url(part.search_query, part.max_price) for part in parts}
    client = ApifyClientAsync(get_settings().apify_api_token)
    results = await run_searches(client, list(urls.values()), details)

    for _ in range(MAX_RETRIES):
        empty = [url for url in urls.values() if not results[url]]
        if not empty:
            break
        results.update(await run_searches(client, empty, details))
    return {category: results[url] for category, url in urls.items()}
