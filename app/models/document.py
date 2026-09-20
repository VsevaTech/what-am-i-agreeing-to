"""Page-aware representation of an uploaded document."""

from pydantic import BaseModel, Field


class Page(BaseModel):
    number: int = Field(ge=1)
    text: str


class ExtractedDocument(BaseModel):
    source_kind: str  # "pdf" | "text"
    filename: str | None = None
    pages: list[Page]

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def char_count(self) -> int:
        return sum(len(p.text) for p in self.pages)

    def page(self, number: int) -> Page | None:
        for p in self.pages:
            if p.number == number:
                return p
        return None

    def to_prompt_text(self, max_chars: int | None = None) -> str:
        """Render the document with explicit page markers for the AI prompt."""
        chunks = [f"=== PAGE {p.number} ===\n{p.text.strip()}\n" for p in self.pages]
        text = "\n".join(chunks)
        if max_chars is not None and len(text) > max_chars:
            text = text[:max_chars] + "\n[... document truncated ...]"
        return text
