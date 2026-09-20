"""FastAPI application. Routes stay thin; business logic lives in app/services."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from app.config import Settings, get_settings
from app.models.agreement import CATEGORIES, CATEGORY_LABELS, Status
from app.services import document_extractor as extractor
from app.services.ai.base import AIProvider, AIProviderError
from app.services.ai.factory import build_provider
from app.services.analysis import run_analysis
from app.services.evidence_validator import locate_evidence
from app.services.result_store import ResultStore

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

DISCLAIMER = (
    "This tool helps locate and summarize terms in a document. It is not legal advice. "
    "Always verify important terms against the original agreement."
)
PRIVACY_NOTICE = (
    "Document text will be sent to an external AI provider (Google Gemini) for analysis."
)


def create_app(
    settings: Settings | None = None, provider: AIProvider | None | str = "auto"
) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="What Am I Agreeing To?", version="0.1.0", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    if provider == "auto":
        try:
            provider = build_provider(settings)
        except AIProviderError as exc:
            logger.warning("AI provider not configured: %s", exc)
            provider = None

    app.state.settings = settings
    app.state.provider = provider
    app.state.store = ResultStore(ttl_seconds=settings.result_ttl_seconds)

    def render(request: Request, name: str, status_code: int = 200, **ctx) -> HTMLResponse:
        base = {
            "request": request,
            "disclaimer": DISCLAIMER,
            "privacy_notice": PRIVACY_NOTICE,
            "ai_configured": app.state.provider is not None,
            "max_upload_mb": settings.max_upload_mb,
            "Status": Status,
        }
        base.update(ctx)
        return templates.TemplateResponse(request, name, base, status_code=status_code)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return render(request, "index.html")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "ai_configured": app.state.provider is not None}

    @app.post("/analyze", response_class=HTMLResponse)
    async def analyze(
        request: Request,
        file: Annotated[UploadFile | None, File()] = None,
        text: Annotated[str | None, Form()] = None,
    ) -> HTMLResponse:
        is_htmx = request.headers.get("HX-Request") == "true"
        template = "partials/result.html" if is_htmx else "result.html"
        error_template = "partials/error.html" if is_htmx else "error.html"

        try:
            if file is not None and file.filename:
                data = await file.read(settings.max_upload_bytes + 1)
                document = extractor.extract_pdf(
                    data,
                    filename=file.filename,
                    max_bytes=settings.max_upload_bytes,
                    max_pages=settings.max_pages,
                )
            elif text and text.strip():
                document = extractor.extract_text(text)
            else:
                raise extractor.EmptyDocumentError()
        except extractor.DocumentError as exc:
            return render(request, error_template, status_code=422, message=exc.user_message)

        result = run_analysis(document, app.state.provider)
        token = app.state.store.put(result)
        logger.info(
            "analyzed document: kind=%s pages=%d chars=%d ai_ok=%s",
            document.source_kind,
            document.page_count,
            document.char_count,
            result.ok,
        )
        return render(request, template, result=result, token=token, labels=CATEGORY_LABELS)

    @app.get("/source/{token}/{category}", response_class=HTMLResponse)
    async def source(request: Request, token: str, category: str) -> HTMLResponse:
        if category not in CATEGORIES:
            raise HTTPException(status_code=404, detail="Unknown category")
        result = app.state.store.get(token)
        if result is None:
            raise HTTPException(status_code=404, detail="This analysis has expired.")
        finding = result.analysis.get(category) if result.analysis else None
        if finding is None or finding.page is None or not finding.evidence:
            raise HTTPException(status_code=404, detail="No source evidence for this finding.")
        page = result.document.page(finding.page)
        if page is None:
            raise HTTPException(status_code=404, detail="Page not found.")
        return render(
            request,
            "partials/source.html",
            category=category,
            label=CATEGORY_LABELS[category],
            finding=finding,
            page=page,
            highlighted=highlight(page.text, finding.evidence),
        )

    return app


def highlight(page_text: str, evidence: str) -> Markup:
    """Escape the page text and wrap the located quote in <mark>."""
    span = locate_evidence(page_text, evidence)
    if span is None:
        return Markup(escape(page_text))
    start, end = span
    return Markup(
        f"{escape(page_text[:start])}<mark>{escape(page_text[start:end])}</mark>"
        f"{escape(page_text[end:])}"
    )


app = create_app()
