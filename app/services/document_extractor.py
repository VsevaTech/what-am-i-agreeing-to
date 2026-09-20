"""Page-aware text extraction for PDFs and pasted text. No OCR."""

from __future__ import annotations

import io
import re

import pdfplumber
from pdfminer.pdfparser import PDFSyntaxError

from app.models.document import ExtractedDocument, Page


class DocumentError(Exception):
    """Base class for user-facing extraction problems."""

    user_message = "The document could not be processed."


class InvalidPdfError(DocumentError):
    user_message = "This file is not a valid PDF."


class EmptyDocumentError(DocumentError):
    user_message = "The document is empty."


class NoExtractableTextError(DocumentError):
    user_message = (
        "This document doesn't contain extractable text. OCR is not supported in this MVP."
    )


class FileTooLargeError(DocumentError):
    def __init__(self, limit_mb: int) -> None:
        super().__init__()
        self.user_message = f"The file is too large. The limit is {limit_mb} MB."


class TooManyPagesError(DocumentError):
    def __init__(self, limit: int) -> None:
        super().__init__()
        self.user_message = f"The document has too many pages. The limit is {limit} pages."


_MIN_MEANINGFUL_CHARS = 20


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub("[ \t" + chr(0x00A0) + "]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pdf(
    data: bytes,
    *,
    filename: str | None = None,
    max_bytes: int | None = None,
    max_pages: int | None = None,
) -> ExtractedDocument:
    """Extract text page by page from a text-based PDF."""
    if max_bytes is not None and len(data) > max_bytes:
        raise FileTooLargeError(max_bytes // (1024 * 1024))
    if not data or not data.lstrip().startswith(b"%PDF"):
        raise InvalidPdfError()

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if len(pdf.pages) == 0:
                raise EmptyDocumentError()
            if max_pages is not None and len(pdf.pages) > max_pages:
                raise TooManyPagesError(max_pages)
            pages: list[Page] = []
            for index, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                pages.append(Page(number=index, text=_clean(text)))
    except DocumentError:
        raise
    except (PDFSyntaxError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise InvalidPdfError() from exc
    except Exception as exc:  # pdfminer raises a wide range of internal errors on bad input
        raise InvalidPdfError() from exc

    total = sum(len(p.text) for p in pages)
    if total < _MIN_MEANINGFUL_CHARS:
        raise NoExtractableTextError()

    return ExtractedDocument(source_kind="pdf", filename=filename, pages=pages)


def extract_text(text: str) -> ExtractedDocument:
    """Wrap pasted plain text. Form-feed characters split pages; otherwise one page."""
    cleaned = _clean(text or "")
    if len(cleaned) < _MIN_MEANINGFUL_CHARS:
        raise EmptyDocumentError()
    raw_pages = [p for p in cleaned.split("\f") if p.strip()] if "\f" in cleaned else [cleaned]
    pages = [Page(number=i, text=_clean(p)) for i, p in enumerate(raw_pages, start=1)]
    return ExtractedDocument(source_kind="text", pages=pages)
