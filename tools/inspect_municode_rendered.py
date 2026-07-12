from __future__ import annotations

import argparse
import json

from playwright.sync_api import sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect rendered Municode page structure.")
    parser.add_argument("url")
    args = parser.parse_args()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.goto(args.url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(12_000)
        print("URL", page.url)
        print("TITLE", page.title())
        print("BODY")
        print(page.locator("body").inner_text(timeout=10_000)[:4000])
        elements = page.locator("input, button, a, [role=treeitem], [role=button]").evaluate_all(
            """els => els.slice(0, 260).map((e, i) => ({
                i,
                tag: e.tagName,
                role: e.getAttribute("role"),
                aria: e.getAttribute("aria-label"),
                placeholder: e.getAttribute("placeholder"),
                text: (e.innerText || e.value || "").trim().slice(0, 160),
                href: e.href || ""
            }))"""
        )
        print("ELEMENTS")
        print(json.dumps(elements, indent=2))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
