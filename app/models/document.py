"""Page-aware representation of an uploaded document."""

from __future__ import annotations

from pydantic import BaseModel, Field, computed_field


class Page(BaseModel):
    number: int = Field(ge=1)
    text: str


def _page_chunk(page: Page) -> str:
    return f"=== PAGE {page.number} ===\n{page.text.strip()}\n"


_CHUNK_SEPARATOR = "\n"


class Coverage(BaseModel):
    """How much of a document was actually sent to the AI provider.

    Computed deterministically by the application (`ExtractedDocument.select_for_ai`), never
    by the model. `partial` is the single source of truth for "was anything left out?".
    """

    total_pages: int
    analyzed_pages: int
    total_chars: int
    analyzed_chars: int
    # Set when the last analyzed page had to be cut mid-page (a single page - typically pasted
    # plain text without page breaks - larger than the AI input limit).
    cut_page: int | None = None

    @computed_field
    @property
    def partial(self) -> bool:
        return self.analyzed_chars < self.total_chars or self.analyzed_pages < self.total_pages

    @property
    def last_analyzed_page(self) -> int:
        return self.analyzed_pages

    def reviewed_label(self) -> str:
        """What was reviewed, e.g. "pages 1–37 of 52" or "the first 200,000 of 250,000
        characters". Only meaningful for a partial analysis."""
        if self.cut_page is not None and self.total_pages == 1:
            return f"the first {self.analyzed_chars:,} of {self.total_chars:,} characters"
        if self.cut_page is not None:
            head = (
                f"pages 1–{self.cut_page - 1} and part of page "
                if self.cut_page > 1
                else "part of page "
            )
            return f"{head}{self.cut_page} of {self.total_pages}"
        if self.analyzed_pages == 1:
            return f"page 1 of {self.total_pages}"
        return f"pages 1–{self.analyzed_pages} of {self.total_pages}"

    def summary(self) -> str:
        """One or two human sentences describing what was reviewed."""
        if not self.partial:
            n = self.total_pages
            return f"All {n} page{'' if n == 1 else 's'} were reviewed."
        rest = "pages were" if self.cut_page is None else "text was"
        return f"Reviewed {self.reviewed_label()}. The remaining {rest} not analyzed."


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
        """Render the document with explicit page markers for the AI prompt.

        Callers should pass a document produced by `select_for_ai`, which already fits the
        limit on whole-page boundaries; the hard cut below is only a last-resort safety net.
        """
        text = _CHUNK_SEPARATOR.join(_page_chunk(p) for p in self.pages)
        if max_chars is not None and len(text) > max_chars:
            text = text[:max_chars] + "\n[... document truncated ...]"
        return text

    def select_for_ai(self, max_chars: int | None) -> tuple[ExtractedDocument, Coverage]:
        """Pick the part of the document that fits the AI input limit.

        Whole pages are taken in order while the rendered prompt stays within `max_chars`;
        the first page that would overflow and everything after it are left out. Only when
        not even the first page fits (e.g. pasted text with no page breaks) is that page cut,
        at the last whitespace before the limit.

        Returns the analyzed sub-document (the exact text the AI will see, and therefore the
        only text evidence may be validated against) and its coverage.
        """
        selected: list[Page] = []
        cut_page: int | None = None
        used = 0
        for page in self.pages:
            chunk = len(_page_chunk(page)) + (len(_CHUNK_SEPARATOR) if selected else 0)
            if max_chars is None or used + chunk <= max_chars:
                selected.append(page)
                used += chunk
                continue
            if not selected:
                header = len(_page_chunk(Page(number=page.number, text="")))
                budget = max(max_chars - header, 0)
                text = page.text.strip()[:budget]
                space = max(text.rfind(" "), text.rfind("\n"))
                if space > budget // 2:
                    text = text[:space]
                selected.append(Page(number=page.number, text=text.rstrip()))
                cut_page = page.number
            break

        analyzed = ExtractedDocument(
            source_kind=self.source_kind, filename=self.filename, pages=selected
        )
        coverage = Coverage(
            total_pages=self.page_count,
            analyzed_pages=len(selected),
            total_chars=self.char_count,
            analyzed_chars=analyzed.char_count,
            cut_page=cut_page,
        )
        return analyzed, coverage
