"""Headed browser capture for login/CAPTCHA-gated pages (spec 5.2).

Deliberately NON-automated for the sensitive part: it opens a *visible* browser, lets the
human navigate / log in / solve any challenge themselves, then -- on the operator's cue --
saves the page HTML and a screenshot for later manual review. It never bypasses CAPTCHAs,
rotates proxies, or spoofs fingerprints. Requires ``pip install .[browser]``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app import settings
from app.collectors.base import BaseCollector, CollectResult


class BrowserCapture(BaseCollector):
    key = "browser_capture"

    def capture(self, url: str, label: str, wait_for_enter: bool = True) -> CollectResult:
        skip = self.preflight()
        if skip:
            return self.skip_result(skip)
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except Exception:
            return self.skip_result("browser_capture: install optional dep `pip install .[browser]`")

        result = CollectResult()
        settings.ensure_dirs()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = "".join(c if c.isalnum() else "_" for c in label)[:40]
        html_path = settings.SNAPSHOT_DIR / f"{safe}_{ts}.html"
        png_path = settings.SNAPSHOT_DIR / f"{safe}_{ts}.png"
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=False)
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded")
                if wait_for_enter:
                    input(
                        f"\n[browser_capture] A visible browser opened at:\n  {url}\n"
                        "Navigate / log in / solve any challenge MANUALLY, then press Enter here "
                        "to save a snapshot..."
                    )
                html_path.write_text(page.content(), encoding="utf-8")
                page.screenshot(path=str(png_path), full_page=True)
                browser.close()
            result.logs.append(
                self.log("success", message=f"captured {label}", url=url,
                         snapshot_path=str(html_path), records=1)
            )
        except Exception as exc:  # noqa: BLE001
            result.logs.append(self.log("failure", message=str(exc)[:200], url=url))
        return result

    def collect(self, products: list[dict[str, Any]]) -> CollectResult:  # not used in batch runs
        return self.skip_result("browser_capture is interactive; use the `capture` command")
