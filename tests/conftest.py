from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.config import Settings
from app.main import create_app
from app.models.agreement import AgreementAnalysis, Finding, Status
from app.models.document import ExtractedDocument
from app.services.ai.base import AIProviderError
from app.services.document_extractor import extract_pdf

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def make_pdf(pages: list[str]) -> bytes:
    """Build a small text PDF in memory. An empty string yields a page with no text."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for text in pages:
        y = 800
        for line in text.split("\n"):
            c.drawString(50, y, line)
            y -= 16
        c.showPage()
    c.save()
    return buf.getvalue()


@pytest.fixture
def simple_pdf_bytes() -> bytes:
    return (EXAMPLES / "simple-subscription.pdf").read_bytes()


@pytest.fixture
def simple_document(simple_pdf_bytes: bytes) -> ExtractedDocument:
    return extract_pdf(simple_pdf_bytes, filename="simple-subscription.pdf")


def simple_analysis() -> AgreementAnalysis:
    """A correct structured result for examples/simple-subscription.pdf (quotes exist verbatim)."""
    return AgreementAnalysis(
        payment=Finding(
            status=Status.FOUND,
            summary="$29 per month plus a one-time $49 enrollment fee.",
            evidence="membership fee of $29 per month",
            page=2,
        ),
        automatic_renewal=Finding(
            status=Status.FOUND,
            summary="Yes - renews monthly after the initial term until cancelled.",
            evidence="automatically renews for successive monthly periods unless cancelled",
            page=3,
        ),
        cancellation=Finding(
            status=Status.FOUND,
            summary="Cancel in writing at least 14 days before the next billing date.",
            evidence="cancellation must be submitted at least 14 days before the next Billing Date",
            page=4,
        ),
        commitment=Finding(
            status=Status.FOUND,
            summary="Initial 6-month term.",
            evidence="initial commitment period of 6 months",
            page=2,
        ),
        data_sharing=Finding(
            status=Status.FOUND,
            summary="Personal information may be shared with payment processors and service providers.",
            evidence="Personal information may be shared with payment processors and service providers",
            page=5,
        ),
    )


class FakeProvider:
    name = "fake"

    def __init__(self, result: AgreementAnalysis | None = None, error: Exception | None = None):
        self.result = result or simple_analysis()
        self.error = error
        self.calls = 0

    def analyze(self, document: ExtractedDocument) -> AgreementAnalysis:
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class FailingProvider(FakeProvider):
    def __init__(self, message: str = "boom"):
        super().__init__(error=AIProviderError(message))


@pytest.fixture
def settings() -> Settings:
    return Settings(gemini_api_key=None, max_upload_mb=1, _env_file=None)


@pytest.fixture
def fake_provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def client(settings: Settings, fake_provider: FakeProvider) -> TestClient:
    return TestClient(create_app(settings=settings, provider=fake_provider))


@pytest.fixture
def client_without_ai(settings: Settings) -> TestClient:
    return TestClient(create_app(settings=settings, provider=None))
