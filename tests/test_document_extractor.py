import pytest

from app.services import document_extractor as ex
from tests.conftest import EXAMPLES, make_pdf


def test_pdf_extraction_is_page_aware(simple_pdf_bytes):
    doc = ex.extract_pdf(simple_pdf_bytes, filename="simple-subscription.pdf")
    assert doc.source_kind == "pdf"
    assert doc.filename == "simple-subscription.pdf"
    assert doc.page_count == 5
    assert [p.number for p in doc.pages] == [1, 2, 3, 4, 5]
    assert "$29 per month" in doc.pages[1].text
    assert "automatically renews" in doc.pages[2].text
    assert "14 days before" in doc.pages[3].text
    assert "payment processors" in doc.pages[4].text


def test_page_numbering_matches_pdf_order():
    data = make_pdf(["First page content here.", "Second page content here.", "Third page."])
    doc = ex.extract_pdf(data)
    assert [p.number for p in doc.pages] == [1, 2, 3]
    assert "First" in doc.page(1).text
    assert "Second" in doc.page(2).text
    assert "Third" in doc.page(3).text
    assert doc.page(4) is None


def test_prompt_text_contains_page_markers(simple_document):
    prompt = simple_document.to_prompt_text()
    for n in range(1, 6):
        assert f"=== PAGE {n} ===" in prompt


def test_prompt_text_truncates(simple_document):
    prompt = simple_document.to_prompt_text(max_chars=500)
    assert prompt.endswith("[... document truncated ...]")
    assert len(prompt) < 600


def test_plain_text_input_single_page():
    doc = ex.extract_text("You agree to pay $10 per month.\n\nThis renews automatically.")
    assert doc.source_kind == "text"
    assert doc.page_count == 1
    assert doc.pages[0].number == 1
    assert "$10 per month" in doc.pages[0].text


def test_plain_text_form_feed_splits_pages():
    doc = ex.extract_text("Page one text is here.\fPage two text is here as well.")
    assert doc.page_count == 2
    assert "Page two" in doc.page(2).text


def test_plain_text_normalises_whitespace():
    doc = ex.extract_text("A   term\twith    odd\r\nspacing that is long enough.")
    assert "A term with odd\nspacing" in doc.pages[0].text


def test_empty_text_rejected():
    with pytest.raises(ex.EmptyDocumentError):
        ex.extract_text("   \n  ")


def test_image_only_pdf_rejected():
    data = make_pdf(["", ""])  # pages without any text layer
    with pytest.raises(ex.NoExtractableTextError) as info:
        ex.extract_pdf(data)
    assert "OCR is not supported" in info.value.user_message


def test_invalid_pdf_rejected():
    with pytest.raises(ex.InvalidPdfError):
        ex.extract_pdf(b"this is definitely not a pdf")


def test_corrupt_pdf_body_rejected():
    with pytest.raises(ex.InvalidPdfError):
        ex.extract_pdf(b"%PDF-1.4\n garbage garbage garbage\n%%EOF")


def test_empty_bytes_rejected():
    with pytest.raises(ex.InvalidPdfError):
        ex.extract_pdf(b"")


def test_pdf_with_zero_pages_is_empty():
    zero_pages = (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [] /Count 0 >> endobj\n"
        b"trailer << /Root 1 0 R >>\n%%EOF"
    )
    with pytest.raises((ex.EmptyDocumentError, ex.InvalidPdfError)):
        ex.extract_pdf(zero_pages)


def test_file_too_large_rejected(simple_pdf_bytes):
    with pytest.raises(ex.FileTooLargeError) as info:
        ex.extract_pdf(simple_pdf_bytes, max_bytes=1024)
    assert "too large" in info.value.user_message


def test_too_many_pages_rejected(simple_pdf_bytes):
    with pytest.raises(ex.TooManyPagesError):
        ex.extract_pdf(simple_pdf_bytes, max_pages=2)


@pytest.mark.parametrize(
    "name", ["simple-subscription.pdf", "ambiguous-agreement.pdf", "no-renewal-agreement.pdf"]
)
def test_all_demo_documents_extract(name):
    doc = ex.extract_pdf((EXAMPLES / name).read_bytes())
    assert doc.page_count >= 2
    assert doc.char_count > 500
