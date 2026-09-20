"""Orchestrates extraction -> AI -> validation. Keeps FastAPI routes thin."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.models.agreement import VerifiedAnalysis
from app.models.document import ExtractedDocument
from app.services.ai.base import AIProvider, AIProviderError
from app.services.evidence_validator import verify_analysis

logger = logging.getLogger(__name__)

AI_UNAVAILABLE_MESSAGE = (
    "AI analysis is currently unavailable. The document was extracted successfully, "
    "but automated term analysis could not be completed."
)


@dataclass
class AnalysisResult:
    document: ExtractedDocument
    analysis: VerifiedAnalysis | None
    ai_error: str | None = None

    @property
    def ok(self) -> bool:
        return self.analysis is not None


def run_analysis(document: ExtractedDocument, provider: AIProvider | None) -> AnalysisResult:
    """Never raises for AI problems; returns a result with `ai_error` set instead."""
    if provider is None:
        return AnalysisResult(document, None, AI_UNAVAILABLE_MESSAGE)
    try:
        raw = provider.analyze(document)
    except AIProviderError as exc:
        # Log only the failure class - never the document text.
        logger.warning("AI provider failed: %s: %s", type(exc).__name__, exc)
        return AnalysisResult(document, None, AI_UNAVAILABLE_MESSAGE)
    return AnalysisResult(document, verify_analysis(raw, document))
