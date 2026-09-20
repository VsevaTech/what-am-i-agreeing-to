"""Capture the README screenshots by driving the real app in a headless browser.

The AI step is served by a deterministic stub provider (no network, no API key) so the
screenshots are reproducible and never contain real API output. The stub deliberately returns
one fabricated quote for the ambiguous document to show the evidence validator rejecting it.

Usage:  python scripts/capture_screenshots.py [output_dir]
Requires the dev extras plus `playwright` and a Chromium (`playwright install chromium`).
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import uvicorn
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models.agreement import AgreementAnalysis, Finding, Status  # noqa: E402
from app.models.document import ExtractedDocument  # noqa: E402
from tests.conftest import simple_analysis  # noqa: E402

EXAMPLES = ROOT / "examples"
PORT = 8765


def ambiguous_analysis() -> AgreementAnalysis:
    return AgreementAnalysis(
        payment=Finding(
            status=Status.UNCLEAR,
            summary="Fees are defined in a separate Order Form or Pricing Schedule not included.",
            evidence="pay the fees set out in the applicable Order Form or Pricing Schedule",
            page=1,
        ),
        automatic_renewal=Finding(
            status=Status.UNCLEAR,
            summary="Extension is possible 'on terms to be agreed'; no automatic renewal stated.",
            evidence="may be extended for additional periods on terms to be agreed",
            page=2,
        ),
        # Deliberately fabricated quote: the validator must reject it and hide the claim.
        cancellation=Finding(
            status=Status.FOUND,
            summary="Cancellation requires 30 days notice.",
            evidence="Cancellation requires 30 days notice.",
            page=2,
        ),
        commitment=Finding(
            status=Status.FOUND,
            summary=(
                "Comply with law and the Terms, keep credentials confidential, "
                "be responsible for account activity."
            ),
            evidence=(
                "keep your account credentials confidential, and to be responsible for all "
                "activity under your account"
            ),
            page=2,
        ),
        data_sharing=Finding(status=Status.NOT_FOUND),
    )


class StubProvider:
    name = "stub"

    def analyze(self, document: ExtractedDocument) -> AgreementAnalysis:
        if "Harborline" in document.pages[0].text:
            return ambiguous_analysis()
        return simple_analysis()


def main(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    app = create_app(settings=Settings(_env_file=None), provider=StubProvider())
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    time.sleep(1.5)
    base = f"http://127.0.0.1:{PORT}"

    launch_kwargs = {}
    if os.environ.get("CHROMIUM_PATH"):
        launch_kwargs["executable_path"] = os.environ["CHROMIUM_PATH"]

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        page = browser.new_page(viewport={"width": 1200, "height": 900})

        page.goto(base + "/")
        assert "external AI provider (Google Gemini)" in page.content()
        page.screenshot(path=str(out_dir / "home.png"), full_page=True)

        # Scenario 1: simple subscription -> five FOUND cards with sources.
        page.set_input_files("#file", str(EXAMPLES / "simple-subscription.pdf"))
        page.click("button[type=submit]")
        page.wait_for_selector(".finding", timeout=15000)
        assert page.locator(".finding").count() == 5
        assert page.locator("text=View source").count() == 5
        page.screenshot(path=str(out_dir / "card.png"), full_page=True)

        page.locator(".finding", has_text="How to cancel").locator("text=View source").click()
        page.wait_for_selector("#source-modal:not([hidden]) mark", timeout=10000)
        assert "14 days" in page.locator("#source-body mark").inner_text()
        page.screenshot(path=str(out_dir / "source.png"))
        page.keyboard.press("Escape")

        # Scenario 2: ambiguous agreement -> UNCLEAR / NOT_FOUND, fabricated quote rejected.
        page.goto(base + "/")
        page.set_input_files("#file", str(EXAMPLES / "ambiguous-agreement.pdf"))
        page.click("button[type=submit]")
        page.wait_for_selector(".finding", timeout=15000)
        body = page.content()
        assert "Cancellation requires 30 days notice" not in body, "fabricated quote leaked"
        assert "could not be located on the cited page" in body
        page.screenshot(path=str(out_dir / "ambiguous.png"), full_page=True)
        browser.close()

    server.should_exit = True
    print("screenshots written to", out_dir)


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screenshots")
