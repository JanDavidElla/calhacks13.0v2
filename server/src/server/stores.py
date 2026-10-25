import re
from typing import Any
from urllib.parse import urlencode

import httpx

from server.config import get_settings
from server.models import Offer

SERP_URL = "https://api.brightdata.com/request"
# Searches took 5-36 s in testing. The price shows up next to Better options, which takes
# about 30 s, so a search can take as long without making the shopper wait more
SEARCH_TIMEOUT = 30
# Amazon titles name the product, then list features; the name is what other stores share
MAX_NAME_WORDS = 8
# Google's store name → the name shown to shoppers. Only these stores count: Google Shopping
# also lists unknown sites (one sold a "Ryzen 5 5500" for $67, too low to be real) and
# marketplace sellers, which it names like "Walmart - JumboBuys" or "eBay - eeeshop"
KNOWN_STORES = {
    "Walmart": "Walmart",
    "Target": "Target",
    "Best Buy": "Best Buy",
    "Newegg.com": "Newegg",
    "B&H Photo-Video-Audio": "B&H Photo",
    "Adorama": "Adorama",
    "Micro Center": "Micro Center",
    "Costco": "Costco",
    "The Home Depot": "The Home Depot",
    "Lowe's": "Lowe's",
    "Staples": "Staples",
    "Macy's": "Macy's",
    "Kohl's": "Kohl's",
    "Wayfair": "Wayfair",
    "IKEA": "IKEA",
    "GameStop": "GameStop",
    "Apple": "Apple",
    "Dell": "Dell",
    "Lenovo": "Lenovo",
    "Samsung": "Samsung",
}
# Google tags listings that aren't new, e.g. "Pre-owned" or "Refurbished, 14% OFF"
NOT_NEW = re.compile(r"pre-owned|refurbished|renewed|used|open box", re.IGNORECASE)
PRICE = re.compile(r"\$([\d,]+(?:\.\d+)?)")


class StoresUnavailable(Exception):
    """The server has no Bright Data key, so it can't check other stores."""


class StoreSearchFailed(Exception):
    """Bright Data couldn't get the Google Shopping results."""


def shopping_url(query: str) -> str:
    # brd_json asks Bright Data for parsed results whatever the zone's format setting is;
    # gl and hl keep prices in US dollars
    params = {"q": query, "tbm": "shop", "gl": "us", "hl": "en", "brd_json": 1}
    return f"https://www.google.com/search?{urlencode(params)}"


def product_name(title: str) -> str:
    """The start of an Amazon title, before the first comma, colon, bracket or dash."""
    # Trademark signs change Google's results: "Ryzen™ 5 5500" missed Newegg's listing
    name = re.sub(r"[™®©]", "", re.split(r"[,:(|]| - ", title)[0])
    return " ".join(name.split()[:MAX_NAME_WORDS])


def to_offer(row: dict[str, Any]) -> Offer | None:
    """Convert a Google Shopping result to an Offer, skipping unknown stores and used items."""
    store = KNOWN_STORES.get(row.get("shop", ""))
    price = PRICE.search(row.get("price", ""))
    # A foreign price means the store sells in another currency and ships from abroad
    if store is None or price is None or row.get("foreign_price") or NOT_NEW.search(row.get("tag", "")):
        return None
    return Offer(store=store, title=row["title"], price=float(price[1].replace(",", "")), url=row["link"])


async def search_stores(title: str) -> list[Offer]:
    """Search Google Shopping for an Amazon product and return new listings from known stores."""
    settings = get_settings()
    # An empty BRIGHTDATA_API_KEY= line in .env counts as not set
    if not settings.brightdata_api_key:
        raise StoresUnavailable("Price checks at other stores aren't set up on this server.")

    # Google often shows Bright Data a captcha, and Bright Data won't repeat a failed search
    # for 15 s, so a retry searches the full title instead of the product's name
    queries = dict.fromkeys([product_name(title), title])
    async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as client:
        for query in queries:
            try:
                response = await client.post(
                    SERP_URL,
                    headers={"Authorization": f"Bearer {settings.brightdata_api_key}"},
                    json={"zone": settings.brightdata_serp_zone, "url": shopping_url(query), "format": "raw"},
                )
                response.raise_for_status()
            except httpx.HTTPError as e:
                # Not retried: a timeout already used up the time limit
                raise StoreSearchFailed(f"Google Shopping search failed ({type(e).__name__}). Try again.") from e
            # A failed search still answers 200, with an empty body and the error in this header
            if "x-brd-error" not in response.headers:
                return [offer for row in response.json().get("shopping", []) if (offer := to_offer(row))]
    # The short code, e.g. "captcha", when there is one; the full message is a paragraph
    error = response.headers.get("x-brd-error-code") or response.headers["x-brd-error"]
    raise StoreSearchFailed(f"Google Shopping search failed ({error}). Try again.")
