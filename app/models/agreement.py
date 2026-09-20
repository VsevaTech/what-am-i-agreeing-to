"""Structured schema for agreement analysis.

`AgreementAnalysis` is what the AI provider must return (strict JSON, no Markdown).
`VerifiedAnalysis` is what the application shows after deterministic evidence validation.
"""

from enum import StrEnum

from pydantic import BaseModel, Field

CATEGORIES: tuple[str, ...] = (
    "payment",
    "automatic_renewal",
    "cancellation",
    "commitment",
    "data_sharing",
)

CATEGORY_LABELS: dict[str, str] = {
    "payment": "You pay",
    "automatic_renewal": "Automatic renewal",
    "cancellation": "How to cancel",
    "commitment": "You commit to",
    "data_sharing": "Data sharing",
}


class Status(StrEnum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    UNCLEAR = "UNCLEAR"


class Finding(BaseModel):
    """One extracted term, exactly as returned by the AI provider."""

    status: Status = Field(description="FOUND, NOT_FOUND or UNCLEAR.")
    summary: str = Field(
        default="",
        description=(
            "One short factual sentence restating what the document says. "
            "Empty when status is NOT_FOUND. No advice, no opinions."
        ),
    )
    evidence: str | None = Field(
        default=None,
        description=(
            "The shortest verbatim quote from the document (max ~40 words) that supports the "
            "summary. Must be copied exactly. Null when nothing was found."
        ),
    )
    page: int | None = Field(
        default=None,
        description="1-based page number where the evidence quote appears. Null if none.",
    )


class AgreementAnalysis(BaseModel):
    """Fixed five-category schema. The AI must not add or omit categories."""

    payment: Finding
    automatic_renewal: Finding
    cancellation: Finding
    commitment: Finding
    data_sharing: Finding

    def get(self, category: str) -> Finding:
        return getattr(self, category)


class VerifiedFinding(Finding):
    """A finding after evidence validation against the source document."""

    note: str | None = Field(
        default=None,
        description="Explanation added by the application (e.g. why the status became UNCLEAR).",
    )
    evidence_verified: bool = False


class VerifiedAnalysis(BaseModel):
    payment: VerifiedFinding
    automatic_renewal: VerifiedFinding
    cancellation: VerifiedFinding
    commitment: VerifiedFinding
    data_sharing: VerifiedFinding

    def get(self, category: str) -> VerifiedFinding:
        return getattr(self, category)

    def items(self) -> list[tuple[str, str, VerifiedFinding]]:
        return [(c, CATEGORY_LABELS[c], self.get(c)) for c in CATEGORIES]

    def unresolved(self) -> list[tuple[str, str, VerifiedFinding]]:
        return [(c, label, f) for c, label, f in self.items() if f.status is not Status.FOUND]
