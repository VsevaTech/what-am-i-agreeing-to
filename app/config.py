"""Application settings. All secrets come from environment variables only."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    gemini_api_key: str | None = None
    # The model is configurable; nothing else in the project references a model name.
    gemini_model: str = "gemini-2.5-flash"
    ai_timeout_seconds: float = 60.0

    max_upload_mb: int = 10
    max_pages: int = 60
    # Analysed documents live in memory only, for this long, so the source viewer can work.
    result_ttl_seconds: int = 1800
    # Upper bound on the characters sent to the AI provider.
    max_ai_chars: int = 200_000

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
