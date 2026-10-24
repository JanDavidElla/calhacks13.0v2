from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

import server.amazon as amazon
from server.amazon import search_parts, search_url, to_product
from server.models import PartPlan


def apify_item(asin: str, input_url: str, price: float | None = 50.0, **extra: Any) -> dict[str, Any]:
    return {
        "asin": asin,
        "title": f"Product {asin}",
        "price": None if price is None else {"value": price, "currency": "$"},
        "imageUrl": f"https://img.example/{asin}.jpg",
        "stars": 4.5,
        "input": input_url,
        **extra,
    }


class FakeApify:
    """Stands in for ApifyClientAsync; each Actor run returns the next batch of items."""

    def __init__(self, runs: list[list[dict[str, Any]] | None]) -> None:
        self.runs = runs
        self.searched: list[list[str]] = []
        self.items: list[dict[str, Any]] = []

    def actor(self, actor_id: str) -> "FakeApify":
        return self

    async def call(self, run_input: dict[str, Any], **kwargs: Any) -> SimpleNamespace | None:
        self.searched.append([u["url"] for u in run_input["categoryOrProductUrls"]])
        items = self.runs.pop(0)
        if items is None:
            return None
        self.items = items
        return SimpleNamespace(default_dataset_id="dataset-id")

    def dataset(self, dataset_id: str) -> "FakeApify":
        return self

    async def list_items(self) -> SimpleNamespace:
        return SimpleNamespace(items=self.items)


def use_fake_apify(monkeypatch: pytest.MonkeyPatch, runs: list[list[dict[str, Any]] | None]) -> FakeApify:
    fake = FakeApify(runs)
    monkeypatch.setattr(amazon, "ApifyClientAsync", lambda token: fake)
    return fake


CPU = PartPlan(category="CPU", search_query="ryzen 5", max_price=100)
GPU = PartPlan(category="GPU", search_query="rtx 3060", max_price=200)


def test_search_url_applies_price_headroom_in_cents() -> None:
    query = parse_qs(urlparse(search_url("ryzen 5 & more", 100)).query)
    assert query == {"k": ["ryzen 5 & more"], "rh": ["p_36:-15000"]}


def test_to_product_maps_fields_and_builds_amazon_link() -> None:
    product = to_product(apify_item("B0TEST", "url", price=99.5))
    assert product is not None
    assert product.model_dump() == {
        "asin": "B0TEST",
        "title": "Product B0TEST",
        "price": 99.5,
        "url": "https://www.amazon.com/dp/B0TEST",
        "image": "https://img.example/B0TEST.jpg",
        "stars": 4.5,
        "details": None,  # search results never include page details
    }


@pytest.mark.parametrize(
    "item",
    [
        apify_item("B0TEST", "url", price=None),
        apify_item("B0TEST", "url", error="product_not_found"),
        {"title": "No ASIN", "price": {"value": 10}},
    ],
    ids=["no price", "error item", "no asin"],
)
def test_to_product_skips_unusable_items(item: dict[str, Any]) -> None:
    assert to_product(item) is None


def test_to_product_allows_missing_image_and_rating() -> None:
    item = apify_item("B0TEST", "url")
    del item["imageUrl"], item["stars"]
    product = to_product(item)
    assert product is not None and product.image is None and product.stars is None


@pytest.mark.anyio
async def test_search_parts_groups_results_by_category_in_one_run(monkeypatch: pytest.MonkeyPatch) -> None:
    cpu_url, gpu_url = search_url("ryzen 5", 100), search_url("rtx 3060", 200)
    fake = use_fake_apify(monkeypatch, [[
        apify_item("CPU1", cpu_url),
        apify_item("GPU1", gpu_url),
        apify_item("CPU2", cpu_url),
        apify_item("NOPRICE", gpu_url, price=None),
    ]])

    results = await search_parts([CPU, GPU])

    assert fake.searched == [[cpu_url, gpu_url]]
    assert [p.asin for p in results["CPU"]] == ["CPU1", "CPU2"]
    assert [p.asin for p in results["GPU"]] == ["GPU1"]


@pytest.mark.anyio
async def test_search_parts_retries_only_empty_searches_once(monkeypatch: pytest.MonkeyPatch) -> None:
    cpu_url, gpu_url = search_url("ryzen 5", 100), search_url("rtx 3060", 200)
    fake = use_fake_apify(monkeypatch, [
        [apify_item("CPU1", cpu_url)],
        [apify_item("GPU1", gpu_url)],
    ])

    results = await search_parts([CPU, GPU])

    assert fake.searched == [[cpu_url, gpu_url], [gpu_url]]
    assert [p.asin for p in results["GPU"]] == ["GPU1"]


@pytest.mark.anyio
async def test_search_parts_keeps_retrying_until_results_appear(monkeypatch: pytest.MonkeyPatch) -> None:
    cpu_url, gpu_url = search_url("ryzen 5", 100), search_url("rtx 3060", 200)
    fake = use_fake_apify(monkeypatch, [
        [apify_item("CPU1", cpu_url)],
        [],
        [apify_item("GPU1", gpu_url)],
    ])

    results = await search_parts([CPU, GPU])

    assert fake.searched == [[cpu_url, gpu_url], [gpu_url], [gpu_url]]
    assert [p.asin for p in results["CPU"]] == ["CPU1"]
    assert [p.asin for p in results["GPU"]] == ["GPU1"]


@pytest.mark.anyio
async def test_search_parts_gives_up_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = use_fake_apify(monkeypatch, [None] + [[]] * amazon.MAX_RETRIES)

    results = await search_parts([CPU, GPU])

    assert len(fake.searched) == 1 + amazon.MAX_RETRIES
    assert results == {"CPU": [], "GPU": []}
