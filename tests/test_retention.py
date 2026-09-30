"""Delete analysis now, TTL retention and no-store caching for result / source pages."""

import gc
import re
import weakref

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.analysis import run_analysis
from app.services.result_store import ResultStore
from tests.conftest import EXAMPLES, KeywordProvider

NO_STORE = "no-store, private"


def analyze(client, pdf_bytes, name="simple-subscription.pdf"):
    r = client.post(
        "/analyze",
        files={"file": (name, pdf_bytes, "application/pdf")},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    token = re.search(r'action="/results/([^/"]+)/delete"', r.text).group(1)
    return r, token


# --- ResultStore --------------------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def result_for(text: str):
    from app.services.document_extractor import extract_text

    return run_analysis(extract_text(text), None)


def test_store_delete_removes_entry_and_reports_it():
    store = ResultStore()
    token = store.put(result_for("Members pay $5 per week under this agreement."))
    assert store.get(token) is not None
    assert store.delete(token) is True
    assert store.get(token) is None
    assert store.delete(token) is False  # second delete is safe
    assert len(store) == 0


def test_store_delete_unknown_token_is_false():
    assert ResultStore().delete("never-existed") is False


def test_store_holds_the_only_reference():
    """Deleting drops the whole AnalysisResult (document text, pages, findings, quotes)."""
    store = ResultStore()
    result = result_for("Members pay $5 per week under this agreement.")
    ref = weakref.ref(result)
    token = store.put(result)
    del result
    gc.collect()
    assert ref() is not None
    store.delete(token)
    gc.collect()
    assert ref() is None


def test_deleting_a_does_not_affect_b():
    store = ResultStore()
    a = store.put(result_for("Document A says members pay $5 per week."))
    b = store.put(result_for("Document B says members pay $9 per week."))
    assert store.delete(a)
    assert store.get(a) is None
    assert "Document B" in store.get(b).document.pages[0].text


def test_ttl_cleanup_still_works():
    clock = Clock()
    store = ResultStore(ttl_seconds=60, clock=clock)
    old = store.put(result_for("Old document says members pay $5 per week."))
    clock.now += 30
    fresh = store.put(result_for("Fresh document says members pay $9 per week."))
    clock.now += 31  # old is 61s old, fresh 31s
    assert store.get(old) is None
    assert store.get(fresh) is not None
    assert store.delete(old) is False  # expired entries delete safely too
    clock.now += 30
    assert store.get(fresh) is None


# --- HTTP ---------------------------------------------------------------------------------------


def test_result_url_is_pushed_and_accessible(client, simple_pdf_bytes):
    r, token = analyze(client, simple_pdf_bytes)
    assert r.headers["HX-Push-Url"] == f"/results/{token}"
    page = client.get(f"/results/{token}")
    assert page.status_code == 200
    assert "<html" in page.text and "Agreement card" in page.text
    assert "Delete analysis now" in page.text
    assert "Automatically deleted after 30 minutes" in page.text


def test_delete_flow_removes_result_and_source(client, simple_pdf_bytes):
    _, token = analyze(client, simple_pdf_bytes)
    assert client.get(f"/source/{token}/cancellation").status_code == 200

    r = client.post(f"/results/{token}/delete", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/?deleted=1"
    landing = client.get(r.headers["location"])
    assert "Analysis deleted" in landing.text
    assert "document text, pages, findings and quotes were removed" in landing.text

    gone = client.get(f"/results/{token}")
    assert gone.status_code == 404
    assert "deleted or has expired" in gone.text
    assert "$29 per month" not in gone.text
    for category in ("payment", "cancellation", "data_sharing"):
        s = client.get(f"/source/{token}/{category}")
        assert s.status_code == 404
        assert "Early Termination" not in s.text
    assert token not in client.app.state.store


def test_second_delete_is_safe(client, simple_pdf_bytes):
    _, token = analyze(client, simple_pdf_bytes)
    assert client.post(f"/results/{token}/delete", follow_redirects=False).status_code == 303
    again = client.post(f"/results/{token}/delete", follow_redirects=False)
    assert again.status_code == 303
    assert again.headers["location"] == "/?deleted=0"
    assert "already been deleted or had expired" in client.get("/?deleted=0").text
    assert client.post("/results/garbage-token/delete").status_code == 200  # follows to /


def test_get_never_deletes(client, simple_pdf_bytes):
    _, token = analyze(client, simple_pdf_bytes)
    assert client.get(f"/results/{token}/delete").status_code == 405
    assert client.get(f"/results/{token}").status_code == 200


def test_deleting_one_http_analysis_keeps_the_other(client, simple_pdf_bytes):
    _, a = analyze(client, simple_pdf_bytes)
    _, b = analyze(client, simple_pdf_bytes)
    client.post(f"/results/{a}/delete")
    assert client.get(f"/results/{a}").status_code == 404
    assert client.get(f"/results/{b}").status_code == 200
    assert client.get(f"/source/{b}/cancellation").status_code == 200


def test_expired_result_is_unavailable(settings, fake_provider, simple_pdf_bytes):
    clock = Clock()
    app = create_app(settings=settings, provider=fake_provider)
    app.state.store = ResultStore(ttl_seconds=settings.result_ttl_seconds, clock=clock)
    client = TestClient(app)
    _, token = analyze(client, simple_pdf_bytes)
    clock.now += settings.result_ttl_seconds + 1
    assert client.get(f"/results/{token}").status_code == 404
    assert client.get(f"/source/{token}/cancellation").status_code == 404


def test_ai_unavailable_result_can_be_deleted_too(client_without_ai, simple_pdf_bytes):
    _, token = analyze(client_without_ai, simple_pdf_bytes)
    assert client_without_ai.get(f"/results/{token}").status_code == 200
    client_without_ai.post(f"/results/{token}/delete")
    assert client_without_ai.get(f"/results/{token}").status_code == 404


# --- caching headers ----------------------------------------------------------------------------


def test_sensitive_responses_are_no_store(client, simple_pdf_bytes):
    r, token = analyze(client, simple_pdf_bytes)
    assert r.headers["cache-control"] == NO_STORE
    full = client.post("/analyze", files={"file": ("s.pdf", simple_pdf_bytes, "application/pdf")})
    assert full.headers["cache-control"] == NO_STORE
    assert client.get(f"/results/{token}").headers["cache-control"] == NO_STORE
    assert client.get(f"/source/{token}/cancellation").headers["cache-control"] == NO_STORE
    # error responses for those paths too (they may echo nothing, but must not be cached)
    assert client.get("/results/nope").headers["cache-control"] == NO_STORE
    assert client.get("/source/nope/payment").headers["cache-control"] == NO_STORE
    d = client.post(f"/results/{token}/delete", follow_redirects=False)
    assert d.headers["cache-control"] == NO_STORE


def test_static_assets_are_not_no_store(client):
    r = client.get("/static/style.css")
    assert r.status_code == 200
    assert "no-store" not in r.headers.get("cache-control", "")


# --- coverage states in the UI ------------------------------------------------------------------


@pytest.fixture
def keyword_client() -> TestClient:
    return TestClient(create_app(settings=Settings(_env_file=None), provider=KeywordProvider()))


def test_ui_full_document_analyzed(keyword_client):
    data = (EXAMPLES / "no-cancellation-terms.pdf").read_bytes()
    r, _ = analyze(keyword_client, data, "no-cancellation-terms.pdf")
    assert "Full document analyzed" in r.text
    assert "All 12 pages were reviewed." in r.text
    assert "Partial analysis" not in r.text
    card = re.search(r"<h3>How to cancel</h3>.*?</article>", r.text, re.S).group(0)
    assert "Not found" in card


def test_ui_partial_analysis_warning_and_unclear(keyword_client):
    data = (EXAMPLES / "long-subscriber-agreement.pdf").read_bytes()
    r, token = analyze(keyword_client, data, "long-subscriber-agreement.pdf")
    assert "Partial analysis" in r.text
    assert "Reviewed pages 1–37 of 52. The remaining pages were not analyzed." in r.text
    assert "Full document analyzed" not in r.text
    card = re.search(r"<h3>How to cancel</h3>.*?</article>", r.text, re.S).group(0)
    assert "Unclear" in card
    assert "Not found in this document" not in card
    assert "not found in the analyzed portion" in card
    # FOUND before the cutoff keeps a working source link
    s = keyword_client.get(f"/source/{token}/payment")
    assert s.status_code == 200 and "<mark>" in s.text
    # the unanalyzed cancellation has no source to show
    assert keyword_client.get(f"/source/{token}/cancellation").status_code == 404
