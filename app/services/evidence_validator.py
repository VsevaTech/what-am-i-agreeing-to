"""Deterministic evidence validation.

The AI is not the source of truth; the uploaded document is. Every FOUND finding must cite a
quote that really exists on the cited page (after whitespace / punctuation normalisation).
Anything else is downgraded to UNCLEAR and the quote is discarded.

Validation runs against the *analyzed* document - exactly the text the AI was given - so a
quote from a page (or part of a page) that was never sent cannot be confirmed. When the
analysis was partial, NOT_FOUND is not a conclusion the application can stand behind: the term
may sit in the unread part, so it is reported as UNCLEAR instead.
"""

from __future__ import annotations

import re

from app.models.agreement import (
    CATEGORIES,
    AgreementAnalysis,
    Finding,
    Status,
    VerifiedAnalysis,
    VerifiedFinding,
)
from app.models.document import Coverage, ExtractedDocument

MAX_EVIDENCE_CHARS = 600

# Characters that PDF extraction and LLMs commonly render differently (given as code points so
# the mapping is explicit and survives editor / formatter round-trips).
_CHAR_MAP = str.maketrans(
    {
        chr(0x2018): "'",  # left single quote
        chr(0x2019): "'",  # right single quote
        chr(0x201A): "'",  # single low-9 quote
        chr(0x201C): '"',  # left double quote
        chr(0x201D): '"',  # right double quote
        chr(0x201E): '"',  # double low-9 quote
        chr(0x2013): "-",  # en dash
        chr(0x2014): "-",  # em dash
        chr(0x2212): "-",  # minus sign
        chr(0x00A0): " ",  # no-break space
        chr(0x2026): ".",  # ellipsis - single char so offsets stay aligned with the original
    }
)

_ADVICE_PATTERNS = re.compile(
    r"\b(you should|you shouldn't|do not sign|don't sign|unfair|bad deal|good deal|"
    r"is safe|is risky|dangerous|legally binding|we recommend|i recommend|"
    r"predatory|red flag|beware)\b",
    re.IGNORECASE,
)


def normalize(text: str) -> str:
    text = text.translate(_CHAR_MAP)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def _flexible_pattern(evidence: str) -> re.Pattern[str]:
    """Build a regex matching the quote with any whitespace between tokens."""
    tokens = normalize(evidence).split(" ")
    parts = [re.escape(t) for t in tokens if t]
    return re.compile(r"\s*".join(parts) if len(parts) == 1 else r"\s+".join(parts), re.IGNORECASE)


def locate_evidence(page_text: str, evidence: str) -> tuple[int, int] | None:
    """Return the (start, end) span of the quote in the original page text, or None."""
    if not evidence or not evidence.strip():
        return None
    translated = page_text.translate(_CHAR_MAP)
    match = _flexible_pattern(evidence).search(translated)
    if match:
        return match.start(), match.end()
    return None


def evidence_exists(page_text: str, evidence: str) -> bool:
    return locate_evidence(page_text, evidence) is not None


def contains_advice(text: str | None) -> bool:
    return bool(text and _ADVICE_PATTERNS.search(text))


def partial_not_found_note(coverage: Coverage) -> str:
    return (
        "This term was not found in the analyzed portion of the document. "
        f"The document was only partially analyzed ({coverage.reviewed_label()}), "
        "so it may appear in the part that was not reviewed."
    )


def verify_finding(
    finding: Finding, document: ExtractedDocument, coverage: Coverage | None = None
) -> VerifiedFinding:
    """Validate one finding against `document` - the text that was actually analyzed.

    `coverage` (optional) describes how that text relates to the full upload; it only refines
    the explanation shown when a cited page lies outside the analyzed range.
    """
    verified = VerifiedFinding(**finding.model_dump())

    if contains_advice(verified.summary):
        verified.summary = ""
        verified.note = (
            "The AI summary contained advice rather than an extracted term and was removed."
        )
        if verified.status is Status.FOUND:
            verified.status = Status.UNCLEAR

    if verified.status is Status.NOT_FOUND:
        verified.evidence = None
        verified.page = None
        return verified

    evidence = (verified.evidence or "").strip()
    if not evidence:
        verified.evidence = None
        verified.page = None
        if verified.status is Status.FOUND:
            # An unsupported claim is never shown as a finding.
            verified.status = Status.UNCLEAR
            verified.summary = ""
            verified.note = "The AI reported a term but did not cite supporting text."
        return verified

    if len(evidence) > MAX_EVIDENCE_CHARS:
        return _reject(verified, "The cited passage was too long to be treated as a minimal quote.")

    page = document.page(verified.page) if verified.page is not None else None
    if page is None:
        if (
            coverage is not None
            and coverage.partial
            and verified.page is not None
            and verified.page <= coverage.total_pages
        ):
            return _reject(
                verified,
                f"The AI cited page {verified.page}, which was not part of the analyzed "
                f"portion (pages 1–{coverage.last_analyzed_page}), so this finding could "
                "not be confirmed.",
            )
        return _reject(verified, "The cited page does not exist in the document.")

    if not evidence_exists(page.text, evidence):
        return _reject(
            verified,
            "The quoted text could not be located on the cited page, so this finding "
            "could not be confirmed.",
        )

    verified.evidence = evidence
    verified.evidence_verified = True
    return verified


def _reject(verified: VerifiedFinding, note: str) -> VerifiedFinding:
    """Drop the quote AND the summary: a claim whose evidence failed is not shown at all."""
    verified.status = Status.UNCLEAR
    verified.summary = ""
    verified.evidence = None
    verified.page = None
    verified.evidence_verified = False
    verified.note = note
    return verified


def apply_coverage(finding: VerifiedFinding, coverage: Coverage | None) -> VerifiedFinding:
    """Partial analysis + NOT_FOUND -> UNCLEAR. FOUND and UNCLEAR are left untouched."""
    if coverage is None or not coverage.partial or finding.status is not Status.NOT_FOUND:
        return finding
    finding.status = Status.UNCLEAR
    finding.summary = ""
    finding.evidence = None
    finding.page = None
    finding.evidence_verified = False
    finding.note = partial_not_found_note(coverage)
    return finding


def verify_analysis(
    analysis: AgreementAnalysis,
    document: ExtractedDocument,
    coverage: Coverage | None = None,
) -> VerifiedAnalysis:
    """Validate every category against the analyzed text, then apply the coverage rule.

    `document` must be the analyzed document (see `ExtractedDocument.select_for_ai`). With no
    `coverage` the document is treated as fully analyzed.
    """
    return VerifiedAnalysis(
        **{
            c: apply_coverage(verify_finding(analysis.get(c), document, coverage), coverage)
            for c in CATEGORIES
        }
    )
