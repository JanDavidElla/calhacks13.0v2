import pytest

from server.config import get_settings


@pytest.fixture(autouse=True)
def fake_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use fake API keys so tests never reach real services, even with a .env present."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("XAI_API_KEY", "test-xai-key")
    monkeypatch.setenv("APIFY_API_TOKEN", "test-apify-token")
    get_settings.cache_clear()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
