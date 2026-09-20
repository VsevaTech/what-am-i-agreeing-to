from app.models.agreement import Finding, Status
from app.models.document import ExtractedDocument, Page
from app.services import evidence_validator as ev
from tests.conftest import simple_analysis

DOC = ExtractedDocument(
    source_kind="text",
    pages=[
        Page(number=1, text="Introduction.\nThe fee is $12 per month, billed in advance."),
        Page(
            number=2,
            text=(
                "Renewal.\nThis Agreement automatically renews for successive\n"
                "monthly periods unless cancelled.  “Notice” must be sent in writing."
            ),
        ),
    ],
)


def test_evidence_exists_exact():
    assert ev.evidence_exists(DOC.page(1).text, "The fee is $12 per month")


def test_evidence_whitespace_normalisation():
    quote = "automatically renews   for successive monthly periods"
    assert ev.evidence_exists(DOC.page(2).text, quote)  # page text has a line break inside


def test_evidence_case_and_quote_normalisation():
    assert ev.evidence_exists(DOC.page(2).text, '"notice" must be sent in writing')


def test_locate_returns_span_in_original_text():
    span = ev.locate_evidence(DOC.page(2).text, "renews for successive monthly periods")
    assert span is not None
    start, end = span
    assert DOC.page(2).text[start:end] == "renews for successive\nmonthly periods"


def test_fake_evidence_rejected():
    assert not ev.evidence_exists(DOC.page(1).text, "Cancellation requires 30 days notice.")


def test_found_with_valid_evidence_is_kept():
    f = Finding(status=Status.FOUND, summary="$12 per month", evidence="$12 per month", page=1)
    v = ev.verify_finding(f, DOC)
    assert v.status is Status.FOUND
    assert v.evidence_verified is True
    assert v.evidence == "$12 per month"
    assert v.page == 1
    assert v.note is None


def test_critical_fabricated_quote_becomes_unclear():
    """The AI returns a plausible claim and quote, but the quote is not in the document."""
    f = Finding(
        status=Status.FOUND,
        summary="Cancellation requires 30 days notice.",
        evidence="Cancellation requires 30 days notice.",
        page=1,
    )
    v = ev.verify_finding(f, DOC)
    assert v.status is Status.UNCLEAR
    assert v.evidence is None
    assert v.summary == ""  # the unsupported claim is not displayed at all
    assert v.evidence_verified is False
    assert "could not be located" in v.note


def test_wrong_page_rejected():
    f = Finding(status=Status.FOUND, summary="$12 per month", evidence="$12 per month", page=2)
    v = ev.verify_finding(f, DOC)
    assert v.status is Status.UNCLEAR
    assert v.evidence is None


def test_nonexistent_page_rejected():
    f = Finding(status=Status.FOUND, summary="$12 per month", evidence="$12 per month", page=9)
    v = ev.verify_finding(f, DOC)
    assert v.status is Status.UNCLEAR
    assert "does not exist" in v.note


def test_found_without_evidence_becomes_unclear():
    f = Finding(status=Status.FOUND, summary="$12 per month", evidence=None, page=None)
    v = ev.verify_finding(f, DOC)
    assert v.status is Status.UNCLEAR
    assert "did not cite" in v.note


def test_found_with_blank_evidence_becomes_unclear():
    f = Finding(status=Status.FOUND, summary="$12 per month", evidence="   ", page=1)
    assert ev.verify_finding(f, DOC).status is Status.UNCLEAR


def test_not_found_is_preserved_and_cleaned():
    f = Finding(status=Status.NOT_FOUND, summary="", evidence="stray", page=1)
    v = ev.verify_finding(f, DOC)
    assert v.status is Status.NOT_FOUND
    assert v.evidence is None
    assert v.page is None


def test_unclear_with_real_quote_keeps_quote():
    f = Finding(
        status=Status.UNCLEAR,
        summary="Renewal terms depend on undefined notice.",
        evidence="unless cancelled",
        page=2,
    )
    v = ev.verify_finding(f, DOC)
    assert v.status is Status.UNCLEAR
    assert v.evidence == "unless cancelled"
    assert v.evidence_verified is True


def test_unclear_with_fake_quote_drops_quote():
    f = Finding(status=Status.UNCLEAR, summary="x", evidence="not in the text", page=2)
    v = ev.verify_finding(f, DOC)
    assert v.status is Status.UNCLEAR
    assert v.evidence is None


def test_overlong_evidence_rejected():
    f = Finding(status=Status.FOUND, summary="x", evidence="a " * 400, page=1)
    v = ev.verify_finding(f, DOC)
    assert v.status is Status.UNCLEAR
    assert "too long" in v.note


def test_advice_in_summary_is_removed():
    f = Finding(
        status=Status.FOUND,
        summary="You should not sign this, the fee is unfair.",
        evidence="$12 per month",
        page=1,
    )
    v = ev.verify_finding(f, DOC)
    assert v.status is Status.UNCLEAR
    assert v.summary == ""
    assert "advice" in v.note


def test_verify_analysis_all_categories(simple_document):
    verified = ev.verify_analysis(simple_analysis(), simple_document)
    for _category, _label, finding in verified.items():
        assert finding.status is Status.FOUND
        assert finding.evidence_verified
    assert verified.unresolved() == []


def test_verify_analysis_mixed(simple_document):
    analysis = simple_analysis()
    analysis.cancellation.evidence = "Cancellation requires 30 days notice."
    analysis.data_sharing.status = Status.NOT_FOUND
    verified = ev.verify_analysis(analysis, simple_document)
    assert verified.cancellation.status is Status.UNCLEAR
    assert verified.data_sharing.status is Status.NOT_FOUND
    assert verified.payment.status is Status.FOUND
    assert {c for c, _, _ in verified.unresolved()} == {"cancellation", "data_sharing"}
