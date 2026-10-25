from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# server/.env, resolved from this file so it loads no matter where the server is started
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    # Ignore keys the server doesn't use yet (e.g. CARTESIA_API_KEY), so they can't stop it starting
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    anthropic_api_key: str
    apify_api_token: str
    # Only voice requests use xAI (speech to text), so the server runs without it
    xai_api_key: str | None = None
    # Only the price check at other stores uses Bright Data, so the server runs without it
    brightdata_api_key: str | None = None
    # The SERP API zone made in the Bright Data dashboard
    brightdata_serp_zone: str = "serp_api1"
    # Save every Evaluate-flow answer and replay it for the same request (server.demo_cache)
    demo_cache: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
