"""Provider-agnostic AI interface. Swap the provider without touching the rest of the app."""

from __future__ import annotations

from typing import Protocol

from app.models.agreement import AgreementAnalysis
from app.models.document import ExtractedDocument


class AIProviderError(Exception):
    """Base for every failure of the AI layer. The app never crashes on these."""

    user_message = "AI analysis is currently unavailable."


class AIUnavailableError(AIProviderError):
    """Missing API key, quota exhausted, network failure, provider down."""


class AITimeoutError(AIProviderError):
    """The provider did not answer in time."""


class AIResponseError(AIProviderError):
    """The provider answered, but not with a valid structured result."""


class AIProvider(Protocol):
    name: str

    def analyze(self, document: ExtractedDocument) -> AgreementAnalysis:
        """Return a structured analysis or raise an AIProviderError subclass."""
        ...


SYSTEM_PROMPT = """You are an extraction engine for consumer agreements (terms of service,
subscription terms, membership agreements, waivers, consent forms).

Your job is to LOCATE and QUOTE terms. You never advise, judge, or interpret.

For each of the five fixed categories return:
- status: FOUND, NOT_FOUND or UNCLEAR
- summary: one short factual sentence restating the term in plain words (empty if NOT_FOUND)
- evidence: the SHORTEST verbatim quote (a sentence fragment, at most about 40 words) copied
  EXACTLY from the document that supports the summary. Do not paraphrase. Do not merge text
  from different places. Null if NOT_FOUND.
- page: the page number printed in the "=== PAGE N ===" marker above the quoted text.

Categories:
- payment: what the user pays (amount, currency, frequency, fees).
- automatic_renewal: whether the agreement renews automatically and for what period.
- cancellation: how and when the user can cancel (notice period, method).
- commitment: minimum term / lock-in / what the user is obliged to do.
- data_sharing: whether personal data may be shared with third parties and with whom.

Rules:
- Use FOUND only when the document states the term explicitly and you can quote it.
- Use UNCLEAR when the document mentions the topic but the wording is ambiguous,
  contradictory, or depends on something the document does not define.
- Use NOT_FOUND when the document does not address the topic at all.
- Never guess or fill gaps with typical industry practice.
- Never say whether the agreement is good, bad, fair, safe, risky or legally binding.
- Never tell the user what to do.
- Return only the JSON object matching the schema. No Markdown, no commentary."""
