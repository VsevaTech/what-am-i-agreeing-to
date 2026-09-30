"""Coverage: the application - not the model - decides how much of a document was analyzed,
and a term missing from a partially analyzed document is never reported as NOT_FOUND."""

import pytest

from app.config import Settings
from app.models.agreement import AgreementAnalysis, Finding, Status
from app.models.document import ExtractedDocument, Page
from app.services.analysis import run_analysis
from app.services.document_extractor import extract_pdf, extract_text
from app.services.evidence_validator import verify_analysis
from tests.conftest import EXAMPLES, FakeProvider, KeywordProvider

DEFAULT_LIMIT = Settings(_env_file=None).max_ai_chars


def doc(*texts: str) -> ExtractedDocument:
    return ExtractedDocument(
        source_kind="pdf", pages=[Page(number=i, text=t) for i, t in enumerate(texts, start=1)]
    )


def filler(n: int, tag: str) -> str:
    return (f"Clause {tag} is about service levels and support hours. " * 200)[:n]


def all_not_found() -> AgreementAnalysis:
    return AgreementAnalysis(
        **{
            c: Finding(status=Status.NOT_FOUND)
            for c in ("payment", "automatic_renewal", "cancellation", "commitment", "data_sharing")
        }
    )


@pytest.fixture(scope="module")
def long_document() -> ExtractedDocument:
    return extract_pdf((EXAMPLES / "long-subscriber-agreement.pdf").read_bytes())


@pytest.fixture(scope="module")
def twelve_page_document() -> ExtractedDocument:
    return extract_pdf((EXAMPLES / "no-cancellation-terms.pdf").read_bytes())


# --- deterministic coverage calculation ---------------------------------------------------------


def test_small_document_is_fully_analyzed():
    d = doc("Fee is $5 per month.", "Nothing else.")
    analyzed, cov = d.select_for_ai(10_000)
    assert not cov.partial
    assert (cov.analyzed_pages, cov.total_pages) == (2, 2)
    assert cov.analyzed_chars == cov.total_chars == d.char_count
    assert analyzed.pages == d.pages


def test_no_limit_means_full():
    d = doc(filler(5000, "a"), filler(5000, "b"))
    assert not d.select_for_ai(None)[1].partial


def test_exact_limit_document_is_not_partial():
    d = doc(filler(1000, "a"), filler(1000, "b"), filler(1000, "c"))
    exact = len(d.to_prompt_text())
    _, cov = d.select_for_ai(exact)
    assert not cov.partial
    assert cov.analyzed_pages == 3


def test_one_char_over_limit_is_partial_on_page_boundary():
    d = doc(filler(1000, "a"), filler(1000, "b"), filler(1000, "c"))
    analyzed, cov = d.select_for_ai(len(d.to_prompt_text()) - 1)
    assert cov.partial
    assert (cov.analyzed_pages, cov.total_pages) == (2, 3)
    assert cov.cut_page is None
    # whole pages only: nothing of page 3, pages 1-2 untouched
    assert [p.text for p in analyzed.pages] == [d.pages[0].text, d.pages[1].text]
    assert cov.analyzed_chars == 2000 and cov.total_chars == 3000
    assert cov.summary() == "Reviewed pages 1–2 of 3. The remaining pages were not analyzed."


def test_over_limit_prompt_stays_within_limit_and_is_never_truncated_mid_page():
    d = doc(*[filler(900, str(i)) for i in range(10)])
    analyzed, cov = d.select_for_ai(4000)
    prompt = analyzed.to_prompt_text(4000)
    assert len(prompt) <= 4000
    assert "[... document truncated ...]" not in prompt
    assert cov.partial and cov.analyzed_pages == 4


def test_pages_after_an_oversized_page_are_not_skipped_to():
    """Selection is a contiguous prefix: a small page after the cutoff is not analyzed."""
    d = doc(filler(500, "a"), filler(5000, "big"), "Cancel any time by email.")
    analyzed, cov = d.select_for_ai(2000)
    assert [p.number for p in analyzed.pages] == [1]
    assert cov.partial


def test_plain_text_without_page_breaks_is_cut_by_characters_and_marked_partial():
    text = extract_text(("Members pay $5 per week under this agreement. " * 100).strip())
    assert text.page_count == 1
    analyzed, cov = text.select_for_ai(1000)
    assert cov.partial
    assert cov.cut_page == 1
    assert cov.analyzed_pages == cov.total_pages == 1
    assert cov.analyzed_chars < cov.total_chars
    assert len(analyzed.to_prompt_text()) <= 1000
    assert not analyzed.pages[0].text.endswith(" ")
    assert text.pages[0].text.startswith(analyzed.pages[0].text)
    assert cov.summary().startswith(f"Reviewed the first {cov.analyzed_chars:,} of")


def test_oversized_first_pdf_page_is_cut_and_later_pages_excluded():
    d = doc(filler(3000, "a"), filler(100, "b"))
    _, cov = d.select_for_ai(1000)
    assert cov.cut_page == 1 and cov.partial
    assert cov.reviewed_label() == "part of page 1 of 2"


# --- NOT_FOUND / UNCLEAR / FOUND rules ----------------------------------------------------------


def test_full_document_absent_clause_is_not_found():
    d = doc("You pay $5 per month.", "Other terms.")
    result = run_analysis(d, FakeProvider(result=all_not_found()), max_chars=10_000)
    assert not result.coverage.partial
    assert result.analysis.cancellation.status is Status.NOT_FOUND
    assert result.analysis.cancellation.note is None


def test_partial_document_absent_clause_becomes_unclear():
    d = doc(filler(1000, "a"), filler(1000, "b"), filler(1000, "c"))
    result = run_analysis(d, FakeProvider(result=all_not_found()), max_chars=2100)
    assert result.coverage.partial
    for _c, _label, finding in result.analysis.items():
        assert finding.status is Status.UNCLEAR
        assert finding.evidence is None and finding.page is None
        assert "not found in the analyzed portion" in finding.note
        assert "only partially analyzed (pages 1–2 of 3)" in finding.note


def test_partial_document_valid_found_before_cutoff_is_kept():
    d = doc("You pay a fee of $5 per month.", filler(3000, "b"))
    analysis = all_not_found()
    analysis.payment = Finding(
        status=Status.FOUND, summary="$5 per month", evidence="a fee of $5 per month", page=1
    )
    result = run_analysis(d, FakeProvider(result=analysis), max_chars=500)
    assert result.coverage.partial
    assert result.analysis.payment.status is Status.FOUND
    assert result.analysis.payment.evidence_verified
    assert result.analysis.cancellation.status is Status.UNCLEAR


def test_unclear_is_unchanged_by_coverage():
    d = doc("Fees are set out elsewhere.", filler(3000, "b"))
    analysis = all_not_found()
    analysis.payment = Finding(
        status=Status.UNCLEAR, summary="Defined elsewhere.", evidence="set out elsewhere", page=1
    )
    result = run_analysis(d, FakeProvider(result=analysis), max_chars=500)
    assert result.analysis.payment.status is Status.UNCLEAR
    assert result.analysis.payment.evidence == "set out elsewhere"


@pytest.mark.parametrize("shortfall", [2800, 2400, 1600, 600, 1])
def test_clause_only_after_cutoff_is_never_not_found(shortfall):
    pages = [filler(600, str(i)) for i in range(5)] + ["You may cancel at any time by email."]
    d = doc(*pages)
    result = run_analysis(d, KeywordProvider(), max_chars=len(d.to_prompt_text()) - shortfall)
    assert result.coverage.partial
    assert result.analysis.cancellation.status is not Status.NOT_FOUND
    assert result.analysis.cancellation.status is Status.UNCLEAR


def test_clause_found_once_the_limit_covers_it():
    pages = [filler(600, str(i)) for i in range(5)] + ["You may cancel at any time by email."]
    d = doc(*pages)
    result = run_analysis(d, KeywordProvider(), max_chars=len(d.to_prompt_text()))
    assert not result.coverage.partial
    assert result.analysis.cancellation.status is Status.FOUND
    assert result.analysis.cancellation.page == 6


# --- evidence must come from the analyzed range -------------------------------------------------


def test_real_quote_from_unanalyzed_page_is_rejected(long_document):
    """The quote exists in the upload (page 48) but the AI was never shown page 48."""
    analysis = all_not_found()
    analysis.cancellation = Finding(
        status=Status.FOUND,
        summary="Cancel with 60 days written notice.",
        evidence="may cancel the subscription by giving at least 60 days written",
        page=48,
    )
    result = run_analysis(long_document, FakeProvider(result=analysis), DEFAULT_LIMIT)
    finding = result.analysis.cancellation
    assert finding.status is Status.UNCLEAR
    assert finding.evidence is None and finding.page is None and finding.summary == ""
    assert "page 48, which was not part of the analyzed portion (pages 1–37)" in finding.note


def test_quote_from_unanalyzed_part_of_a_cut_page_is_rejected():
    text = extract_text("Intro text here. " * 60 + "You may cancel by email at any time.")
    analysis = all_not_found()
    analysis.cancellation = Finding(
        status=Status.FOUND, summary="x", evidence="cancel by email at any time", page=1
    )
    result = run_analysis(text, FakeProvider(result=analysis), max_chars=400)
    assert result.coverage.cut_page == 1
    assert result.analysis.cancellation.status is Status.UNCLEAR
    assert "could not be located" in result.analysis.cancellation.note


def test_verify_analysis_without_coverage_behaves_as_before(simple_document):
    from tests.conftest import simple_analysis

    verified = verify_analysis(simple_analysis(), simple_document)
    assert all(f.status is Status.FOUND for _, _, f in verified.items())


# --- regression: the long demo document ---------------------------------------------------------


def test_long_example_cutoff_is_pinned(long_document):
    _, cov = long_document.select_for_ai(DEFAULT_LIMIT)
    assert (cov.analyzed_pages, cov.total_pages) == (37, 52)
    assert cov.partial
    cancel_pages = [p.number for p in long_document.pages if "may cancel" in p.text.lower()]
    renew_pages = [p.number for p in long_document.pages if "renews automatically" in p.text]
    assert cancel_pages == [48] and renew_pages == [49]


def test_provider_only_sees_the_analyzed_pages(long_document):
    provider = KeywordProvider()
    run_analysis(long_document, provider, DEFAULT_LIMIT)
    seen = provider.seen[0]
    assert [p.number for p in seen.pages] == list(range(1, 38))
    prompt = seen.to_prompt_text(DEFAULT_LIMIT)
    assert "=== PAGE 38 ===" not in prompt
    assert "cancellations@lakeshore.example" not in prompt
    assert len(prompt) <= DEFAULT_LIMIT


def test_regression_cancellation_after_cutoff_is_unclear_not_not_found(long_document):
    result = run_analysis(long_document, KeywordProvider(), DEFAULT_LIMIT)
    a = result.analysis
    assert a.cancellation.status is Status.UNCLEAR
    assert a.automatic_renewal.status is Status.UNCLEAR
    assert "not found in the analyzed portion" in a.cancellation.note
    # terms stated before the cutoff are still FOUND with verified quotes
    assert a.payment.status is Status.FOUND and a.payment.page == 2
    assert a.commitment.status is Status.FOUND and a.commitment.page == 3
    assert a.data_sharing.status is Status.FOUND and a.data_sharing.page == 4


def test_twelve_page_example_is_fully_analyzed_and_cancellation_not_found(twelve_page_document):
    result = run_analysis(twelve_page_document, KeywordProvider(), DEFAULT_LIMIT)
    assert not result.coverage.partial
    assert result.coverage.total_pages == 12
    assert result.analysis.cancellation.status is Status.NOT_FOUND
    assert result.analysis.payment.status is Status.FOUND
    assert result.analysis.automatic_renewal.status is Status.FOUND
