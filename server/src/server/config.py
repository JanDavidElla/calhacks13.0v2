from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# server/.env, resolved from this file so it loads no matter where the server is started
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE)

    anthropic_api_key: str
    apify_api_token: str
    # Only voice requests use xAI (speech to text), so the server runs without it
    xai_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
