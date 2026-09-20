"""Google Gemini provider using structured (JSON schema) output."""

from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from app.models.agreement import AgreementAnalysis
from app.models.document import ExtractedDocument
from app.services.ai.base import (
    SYSTEM_PROMPT,
    AIResponseError,
    AITimeoutError,
    AIUnavailableError,
)

logger = logging.getLogger(__name__)


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout_seconds: float = 60.0,
        max_chars: int = 200_000,
        client=None,
    ) -> None:
        if not api_key:
            raise AIUnavailableError("GEMINI_API_KEY is not configured.")
        if not model:
            raise AIUnavailableError("GEMINI_MODEL is not configured.")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_chars = max_chars
        self._client = client
        self._api_key = api_key

    def _get_client(self):
        if self._client is None:
            from google import genai
            from google.genai import types

            self._client = genai.Client(
                api_key=self._api_key,
                http_options=types.HttpOptions(timeout=int(self.timeout_seconds * 1000)),
            )
        return self._client

    def analyze(self, document: ExtractedDocument) -> AgreementAnalysis:
        from google.genai import errors, types

        prompt = (
            "Extract the five categories from the agreement below. Page markers look like "
            "'=== PAGE N ==='.\n\n" + document.to_prompt_text(self.max_chars)
        )
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=AgreementAnalysis,
            temperature=0.0,
        )
        try:
            response = self._get_client().models.generate_content(
                model=self.model, contents=prompt, config=config
            )
        except errors.APIError as exc:
            # 429 = quota, 401/403 = bad key, 5xx = provider down. Never log the key.
            logger.warning("Gemini API error: code=%s status=%s", exc.code, exc.status)
            raise AIUnavailableError(f"Gemini API error ({exc.code}).") from exc
        except TimeoutError as exc:
            raise AITimeoutError("Gemini request timed out.") from exc
        except Exception as exc:  # httpx timeouts / connection errors / SDK internals
            name = type(exc).__name__
            if "Timeout" in name:
                raise AITimeoutError("Gemini request timed out.") from exc
            logger.warning("Gemini request failed: %s", name)
            raise AIUnavailableError(f"Gemini request failed ({name}).") from exc

        return parse_response(response)


def parse_response(response) -> AgreementAnalysis:
    """Turn an SDK response into the schema, rejecting anything that is not valid JSON."""
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, AgreementAnalysis):
        return parsed
    text = getattr(response, "text", None)
    if not text:
        raise AIResponseError("Gemini returned an empty response.")
    try:
        return AgreementAnalysis.model_validate(json.loads(_strip_fences(text)))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise AIResponseError("Gemini returned a response that does not match the schema.") from exc


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()
