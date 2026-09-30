"""Orchestrates extraction -> AI -> validation. Keeps FastAPI routes thin."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.models.agreement import VerifiedAnalysis
from app.models.document import Coverage, ExtractedDocument
from app.services.ai.base import AIProvider, AIProviderError
from app.services.evidence_validator import verify_analysis

logger = logging.getLogger(__name__)

AI_UNAVAILABLE_MESSAGE = (
    "AI analysis is currently unavailable. The document was extracted successfully, "
    "but automated term analysis could not be completed."
)


@dataclass
class AnalysisResult:
    """Everything kept about one analysis. The ResultStore holds only this object, so dropping
    it from the store drops the extracted text, pages, findings, quotes and metadata at once."""

    document: ExtractedDocument
    analysis: VerifiedAnalysis | None
    ai_error: str | None = None
    coverage: Coverage | None = None

    @property
    def ok(self) -> bool:
        return self.analysis is not None


def run_analysis(
    document: ExtractedDocument,
    provider: AIProvider | None,
    max_chars: int | None = None,
) -> AnalysisResult:
    """Never raises for AI problems; returns a result with `ai_error` set instead.

    Coverage is decided here, deterministically: only the whole pages that fit `max_chars` are
    sent to the provider, and evidence is validated against exactly that text. The model is
    never asked whether the document was truncated.
    """
    analyzed, coverage = document.select_for_ai(max_chars)
    if provider is None:
        return AnalysisResult(document, None, AI_UNAVAILABLE_MESSAGE, coverage)
    try:
        raw = provider.analyze(analyzed)
    except AIProviderError as exc:
        # Log only the failure class - never the document text.
        logger.warning("AI provider failed: %s: %s", type(exc).__name__, exc)
        return AnalysisResult(document, None, AI_UNAVAILABLE_MESSAGE, coverage)
    return AnalysisResult(document, verify_analysis(raw, analyzed, coverage), coverage=coverage)
