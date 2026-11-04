"""Render README images with Playwright (dev only).

    whatsapp-agent-ar serve --demo --port 8000 &
    python scripts/screenshot.py http://127.0.0.1:8000/?c=971501110001 assets/hero.png
    python scripts/screenshot.py docs/flow.html assets/flow.png
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def main(url: str, out: str, width: int = 1600, height: int = 900, scale: float = 1) -> None:
    if not url.startswith("http"):
        url = Path(url).resolve().as_uri()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=scale)
        page.goto(url)
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(1200)
        page.screenshot(path=out)
        browser.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    main(args[0], args[1], *(int(a) for a in args[2:4]))
