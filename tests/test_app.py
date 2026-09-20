import re

from app.main import highlight
from app.models.agreement import Status
from tests.conftest import EXAMPLES, make_pdf, simple_analysis


def test_index_shows_privacy_notice_and_disclaimer(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "external AI provider (Google Gemini)" in r.text
    assert "not legal advice" in r.text
    assert "Upload PDF" in r.text
    assert "Paste agreement text" in r.text


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "ai_configured": True}


def test_analyze_pdf_shows_five_cards_with_sources(client, simple_pdf_bytes):
    r = client.post(
        "/analyze",
        files={"file": ("simple-subscription.pdf", simple_pdf_bytes, "application/pdf")},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    for label in ["You pay", "Automatic renewal", "How to cancel", "You commit to", "Data sharing"]:
        assert label in r.text
    assert r.text.count("View source") == 5
    assert "Source: page 4" in r.text
    assert "Unclear / not found" in r.text
    assert "$29 per month" in r.text


def test_analyze_full_page_without_htmx(client, simple_pdf_bytes):
    r = client.post(
        "/analyze",
        files={"file": ("simple-subscription.pdf", simple_pdf_bytes, "application/pdf")},
    )
    assert r.status_code == 200
    assert "<html" in r.text
    assert "Agreement card" in r.text


def test_source_viewer_highlights_evidence(client, simple_pdf_bytes):
    r = client.post(
        "/analyze",
        files={"file": ("simple-subscription.pdf", simple_pdf_bytes, "application/pdf")},
        headers={"HX-Request": "true"},
    )
    match = re.search(r'hx-get="/source/([^/]+)/cancellation"', r.text)
    assert match, "source link for cancellation missing"
    token = match.group(1)
    s = client.get(f"/source/{token}/cancellation")
    assert s.status_code == 200
    assert "Page 4" in s.text
    assert "<mark>" in s.text
    assert re.search(
        r"<mark>cancellation must be submitted at least 14 days.*?</mark>", s.text, re.S
    )
    # Surrounding text of the page is present too
    assert "Early Termination" in s.text


def test_source_viewer_unknown_token_and_category(client):
    assert client.get("/source/doesnotexist/cancellation").status_code == 404
    assert client.get("/source/doesnotexist/bogus").status_code == 404


def test_analyze_pasted_text(client, fake_provider):
    analysis = simple_analysis()
    for category in ("payment", "automatic_renewal", "cancellation", "commitment", "data_sharing"):
        analysis.get(category).status = Status.NOT_FOUND
    analysis.payment.status = Status.FOUND
    analysis.payment.evidence = "$5 per week"
    analysis.payment.page = 1
    fake_provider.result = analysis
    r = client.post(
        "/analyze",
        data={"text": "Members pay $5 per week. Nothing else is stated in this short text."},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert "(pasted text)" in r.text
    assert r.text.count("View source") == 1
    assert "Not found" in r.text


def test_fabricated_evidence_is_shown_as_unclear_not_fact(client, fake_provider, simple_pdf_bytes):
    analysis = simple_analysis()
    analysis.cancellation.summary = "Cancellation requires 30 days notice."
    analysis.cancellation.evidence = "Cancellation requires 30 days notice."
    fake_provider.result = analysis
    r = client.post(
        "/analyze",
        files={"file": ("simple-subscription.pdf", simple_pdf_bytes, "application/pdf")},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert "Unclear" in r.text
    assert "could not be located on the cited page" in r.text
    assert r.text.count("View source") == 4
    # The unverified claim is never rendered - neither as a quote nor as a summary.
    assert "Cancellation requires 30 days notice" not in r.text


def test_ai_unavailable_is_graceful(client_without_ai, simple_pdf_bytes):
    r = client_without_ai.post(
        "/analyze",
        files={"file": ("simple-subscription.pdf", simple_pdf_bytes, "application/pdf")},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert "AI analysis is currently unavailable." in r.text
    assert "The document was extracted successfully" in r.text
    assert "Show extracted text" in r.text
    assert "View source" not in r.text


def test_index_warns_when_ai_not_configured(client_without_ai):
    r = client_without_ai.get("/")
    assert "AI analysis is not configured" in r.text
    assert client_without_ai.get("/health").json()["ai_configured"] is False


def test_invalid_pdf_returns_message(client):
    r = client.post(
        "/analyze",
        files={"file": ("x.pdf", b"not a pdf at all", "application/pdf")},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 422
    assert "not a valid PDF" in r.text


def test_image_only_pdf_returns_message(client):
    r = client.post(
        "/analyze",
        files={"file": ("scan.pdf", make_pdf(["", ""]), "application/pdf")},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 422
    assert "contain extractable text" in r.text
    assert "OCR is not supported" in r.text


def test_file_too_large_returns_message(client):
    big = b"%PDF-1.4\n" + b"0" * (1024 * 1024 + 10)  # settings fixture sets max_upload_mb=1
    r = client.post(
        "/analyze",
        files={"file": ("big.pdf", big, "application/pdf")},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 422
    assert "too large" in r.text


def test_empty_submission_returns_message(client):
    r = client.post("/analyze", data={"text": ""}, headers={"HX-Request": "true"})
    assert r.status_code == 422
    assert "empty" in r.text


def test_demo_documents_available():
    for name in ["simple-subscription.pdf", "ambiguous-agreement.pdf", "no-renewal-agreement.pdf"]:
        assert (EXAMPLES / name).exists()


def test_highlight_escapes_html_and_marks_quote():
    page = "Fees <b>apply</b>. Renewal is\nautomatic unless cancelled."
    html = highlight(page, "renewal is automatic")
    assert "&lt;b&gt;apply&lt;/b&gt;" in html
    assert "<mark>Renewal is\nautomatic</mark>" in html


def test_highlight_without_match_returns_escaped_text():
    html = highlight("plain <text>", "missing")
    assert html == "plain &lt;text&gt;"
