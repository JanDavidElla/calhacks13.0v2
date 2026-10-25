import json
from functools import partial
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

import server.stores as stores
from server.config import get_settings
from server.models import Offer
from server.stores import StoreSearchFailed, StoresUnavailable, search_stores, to_offer


def shopping_row(shop: str = "Newegg.com", price: str = "$99.00", **extra: Any) -> dict[str, Any]:
    return {
        "title": "AMD Ryzen 5 5500 6-Core Processor",
        "price": price,
        "shop": shop,
        "link": "https://www.google.com/search?ibp=oshop&q=AMD+Ryzen+5+5500",
        **extra,
    }


def fake_bright_data(monkeypatch: pytest.MonkeyPatch, *answers: httpx.Response | Exception) -> list[httpx.Request]:
    """Answer the module's HTTP calls in turn: a response, or an error to raise."""
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        result = answers[len(requests) - 1]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(stores.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(answer)))
    return requests


# How Bright Data answers when Google blocked the search
CAPTCHA = httpx.Response(200, headers={"x-brd-error": "Challenge page detected", "x-brd-error-code": "captcha"})
TITLE = "AMD Ryzen™ 5 5500 6-Core, 12-Thread Unlocked Desktop Processor with Wraith Stealth Cooler"


def searched_for(request: httpx.Request) -> str:
    return parse_qs(urlparse(json.loads(request.content)["url"]).query)["q"][0]


def test_keeps_a_new_listing_from_a_known_store() -> None:
    assert to_offer(shopping_row(tag="37% OFF")) == Offer(
        store="Newegg",
        title="AMD Ryzen 5 5500 6-Core Processor",
        price=99.0,
        url="https://www.google.com/search?ibp=oshop&q=AMD+Ryzen+5+5500",
    )


def test_reads_prices_with_thousands_separators() -> None:
    offer = to_offer(shopping_row(shop="Best Buy", price="$1,070"))
    assert offer is not None and offer.price == 1070.0


@pytest.mark.parametrize(
    "row",
    [
        shopping_row(shop="dawsonmusicacademy.org", price="$67.22"),
        shopping_row(shop="Walmart - JumboBuys"),
        shopping_row(tag="Pre-owned"),
        shopping_row(tag="Refurbished, 14% OFF"),
        shopping_row(foreign_price="€60"),
    ],
    ids=["unknown store", "marketplace seller", "pre-owned", "refurbished", "foreign price"],
)
def test_skips_listings_shoppers_cant_trust_to_be_the_same_deal(row: dict[str, Any]) -> None:
    assert to_offer(row) is None


@pytest.mark.anyio
async def test_searches_google_shopping_through_the_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [shopping_row(), shopping_row(shop="Walmart - JumboBuys")]
    requests = fake_bright_data(monkeypatch, httpx.Response(200, json={"shopping": rows}))

    offers = await search_stores(TITLE)

    assert [offer.store for offer in offers] == ["Newegg"]
    body = json.loads(requests[0].content)
    assert requests[0].headers["authorization"] == "Bearer test-brightdata-key"
    assert body["zone"] == "serp_api1"
    assert parse_qs(urlparse(body["url"]).query)["tbm"] == ["shop"]
    # The product's name, without the features after the comma
    assert searched_for(requests[0]) == "AMD Ryzen 5 5500 6-Core"


@pytest.mark.anyio
async def test_retries_a_quietly_failed_search_with_the_full_title(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = fake_bright_data(monkeypatch, CAPTCHA, httpx.Response(200, json={"shopping": [shopping_row()]}))

    offers = await search_stores(TITLE)

    assert [offer.store for offer in offers] == ["Newegg"]
    assert [searched_for(request) for request in requests] == ["AMD Ryzen 5 5500 6-Core", TITLE]


@pytest.mark.anyio
async def test_a_title_that_is_only_a_name_is_searched_once(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = fake_bright_data(monkeypatch, CAPTCHA)

    with pytest.raises(StoreSearchFailed):
        await search_stores("GIGABYTE B550M K")
    assert len(requests) == 1


@pytest.mark.anyio
async def test_two_quiet_failures_raise_store_search_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_bright_data(monkeypatch, CAPTCHA, CAPTCHA)

    # The short error code, not Bright Data's paragraph-long message
    with pytest.raises(StoreSearchFailed, match=r"\(captcha\)"):
        await search_stores(TITLE)


@pytest.mark.anyio
async def test_a_timeout_raises_store_search_failed_without_retrying(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = fake_bright_data(monkeypatch, httpx.ReadTimeout("timed out"))

    with pytest.raises(StoreSearchFailed, match="ReadTimeout"):
        await search_stores(TITLE)
    assert len(requests) == 1


@pytest.mark.anyio
async def test_without_a_key_raises_stores_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "")
    get_settings.cache_clear()

    with pytest.raises(StoresUnavailable):
        await search_stores("AMD Ryzen 5 5500")
