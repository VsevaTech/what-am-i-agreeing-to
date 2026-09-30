"""Deterministic demo: full vs partial coverage, then "Delete analysis now".

Runs the real app (default settings, MAX_AI_CHARS=200000) with an honest keyword stub instead
of Gemini: the stub can only report what is in the pages the application sends it, exactly like
a well-behaved model. No network, no API key.

  A  examples/no-cancellation-terms.pdf     12 pages, fully analyzed, no cancellation clause
  B  examples/long-subscriber-agreement.pdf 52 pages, pages 1-37 analyzed, cancellation on p.48

Usage:
  python scripts/demo_partial.py                      # HTTP checks only
  python scripts/demo_partial.py --screenshots DIR    # + browser screenshots (needs playwright)
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path

import httpx
import uvicorn

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from tests.conftest import KeywordProvider  # noqa: E402

EXAMPLES = ROOT / "examples"
PORT = 8766
logging.getLogger("httpx").setLevel(logging.WARNING)
BASE = f"http://127.0.0.1:{PORT}"
DOC_A = "no-cancellation-terms.pdf"
DOC_B = "long-subscriber-agreement.pdf"


def check(label: str, ok: bool) -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        raise SystemExit(1)


def card(html: str, label: str) -> str:
    match = re.search(rf"<h3>{re.escape(label)}</h3>.*?</article>", html, re.S)
    return match.group(0) if match else ""


def upload(client: httpx.Client, name: str) -> tuple[str, str]:
    r = client.post(
        "/analyze",
        files={"file": (name, (EXAMPLES / name).read_bytes(), "application/pdf")},
        headers={"HX-Request": "true"},
    )
    r.raise_for_status()
    token = r.headers["HX-Push-Url"].rsplit("/", 1)[1]
    return token, r.text


def http_demo() -> None:
    with httpx.Client(base_url=BASE, timeout=120) as client:
        print(f"\nDocument A - {DOC_A}")
        _, html = upload(client, DOC_A)
        check("UI: 'Full document analyzed'", "Full document analyzed" in html)
        check("UI: 'All 12 pages were reviewed.'", "All 12 pages were reviewed." in html)
        check(
            "How to cancel -> Not found",
            "Not found in this document" in card(html, "How to cancel"),
        )

        print(f"\nDocument B - {DOC_B}")
        token, html = upload(client, DOC_B)
        check("UI: 'Partial analysis'", "Partial analysis" in html)
        check(
            "UI: 'Reviewed pages 1–37 of 52.'",
            "Reviewed pages 1–37 of 52. The remaining pages were not analyzed." in html,
        )
        cancel = card(html, "How to cancel")
        check("How to cancel -> Unclear", "? Unclear" in cancel)
        check(
            "... 'not found in the analyzed portion'", "not found in the analyzed portion" in cancel
        )
        check("... never 'Not found'", "Not found in this document" not in cancel)
        check("You pay -> Found (page 2, before cutoff)", "Source: page 2" in card(html, "You pay"))

        result_url, source_url = f"/results/{token}", f"/source/{token}/payment"
        print("\nDelete analysis now")
        check(f"before: GET {result_url} -> 200", client.get(result_url).status_code == 200)
        check(f"before: GET {source_url} -> 200", client.get(source_url).status_code == 200)
        r = client.post(f"{result_url}/delete", follow_redirects=True)
        check("POST delete -> 'Analysis deleted'", "Analysis deleted" in r.text)
        check(f"after:  GET {result_url} -> 404", client.get(result_url).status_code == 404)
        check(f"after:  GET {source_url} -> 404", client.get(source_url).status_code == 404)
        again = client.post(f"{result_url}/delete", follow_redirects=False)
        check("second delete is safe (303)", again.status_code == 303)


def browser_demo(out: Path) -> None:
    from playwright.sync_api import sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        # CHROMIUM_PATH=/path/to/chrome overrides the bundled browser (optional).
        executable = os.environ.get("CHROMIUM_PATH") or None
        browser = p.chromium.launch(executable_path=executable)
        page = browser.new_page(viewport={"width": 1100, "height": 1100})

        def analyze(name: str) -> None:
            page.goto(BASE + "/")
            page.set_input_files("#file", str(EXAMPLES / name))
            page.click("button[type=submit]")
            page.wait_for_selector(".coverage", timeout=60_000)

        analyze(DOC_A)
        page.screenshot(path=str(out / "demo-a-full.png"), full_page=True)

        analyze(DOC_B)
        result_url = page.url
        page.screenshot(path=str(out / "demo-b-partial.png"), full_page=True)
        token = result_url.rsplit("/", 1)[1]

        page.click("summary:has-text('Delete analysis now')")
        page.screenshot(path=str(out / "demo-b-confirm.png"))
        page.click("button:has-text('Yes, delete now')")
        page.wait_for_selector("text=Analysis deleted")
        page.screenshot(path=str(out / "demo-deleted.png"))

        page.goto(result_url)
        page.screenshot(path=str(out / "demo-old-result-url.png"))
        response = page.goto(f"{BASE}/source/{token}/payment")
        page.screenshot(path=str(out / "demo-old-source-url.png"))
        print(f"\nBrowser: {result_url} and its source URL -> {response.status}")
        print(f"Screenshots written to {out}")
        browser.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshots", type=Path, default=None)
    args = parser.parse_args()

    app = create_app(settings=Settings(_env_file=None), provider=KeywordProvider())
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    try:
        http_demo()
        if args.screenshots:
            browser_demo(args.screenshots)
        print("\nDEMO OK")
    finally:
        server.should_exit = True


if __name__ == "__main__":
    main()
