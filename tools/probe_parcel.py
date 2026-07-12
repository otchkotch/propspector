from __future__ import annotations

import json

from playwright.sync_api import sync_playwright


PARCEL = "07-046.40-077"


def pause(page, seconds: int = 20) -> None:
    page.wait_for_timeout(seconds * 1000)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=False, slow_mo=200)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.goto("https://www3.newcastlede.gov/parcel/search/", wait_until="domcontentloaded", timeout=60_000)
        pause(page)
        print("AFTER LOAD URL:", page.url)
        print("AFTER LOAD TITLE:", page.title())
        print("PARCEL INPUT COUNT:", page.locator("#ctl00_ctl00_ContentPlaceHolder1_ContentPlaceHolder1__TextBoxParcelNumber").count())
        page.screenshot(path="probe-search-page.png", full_page=True)
        page.fill("#ctl00_ctl00_ContentPlaceHolder1_ContentPlaceHolder1__TextBoxParcelNumber", "".join(ch for ch in PARCEL if ch.isalnum()))
        page.click("#ctl00_ctl00_ContentPlaceHolder1_ContentPlaceHolder1__ButtonSearch")
        page.wait_for_load_state("domcontentloaded", timeout=60_000)
        pause(page)
        print("URL:", page.url)
        print("TITLE:", page.title())
        elements = page.locator("a, input, button, table, td").evaluate_all(
            """els => els.slice(0, 260).map((e, i) => ({
                i,
                tag: e.tagName,
                id: e.id || null,
                text: (e.innerText || e.value || "").trim().slice(0, 160),
                href: e.href || null,
                type: e.getAttribute("type")
            }))"""
        )
        print(json.dumps(elements, indent=2))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
