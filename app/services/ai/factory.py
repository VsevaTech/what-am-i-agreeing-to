"""Builds the configured AI provider from settings."""

from __future__ import annotations

from app.config import Settings
from app.services.ai.base import AIProvider, AIUnavailableError
from app.services.ai.gemini import GeminiProvider


def build_provider(settings: Settings) -> AIProvider:
    if not settings.gemini_api_key:
        raise AIUnavailableError("GEMINI_API_KEY is not set.")
    return GeminiProvider(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        timeout_seconds=settings.ai_timeout_seconds,
        max_chars=settings.max_ai_chars,
    )
