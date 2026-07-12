from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www3.newcastlede.gov/parcel/search/"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2000)
        print("URL:", page.url)
        print("TITLE:", page.title())
        elements = page.locator("input, button, a, select, label").evaluate_all(
            """els => els.slice(0, 160).map((e, i) => ({
                i,
                tag: e.tagName,
                id: e.id || null,
                name: e.getAttribute("name"),
                type: e.getAttribute("type"),
                text: (e.innerText || e.value || e.getAttribute("aria-label") || e.placeholder || "").trim(),
                href: e.href || null,
                classes: e.className || null
            }))"""
        )
        print(json.dumps(elements, indent=2))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
