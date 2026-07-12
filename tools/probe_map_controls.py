from __future__ import annotations

import json
from pathlib import Path
import re

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright


PARCEL = "0903000082"
SEARCH_URL = "https://www3.newcastlede.gov/parcel/search/"
PARCEL_INPUT = "#ctl00_ctl00_ContentPlaceHolder1_ContentPlaceHolder1__TextBoxParcelNumber"
SEARCH_BUTTON = "#ctl00_ctl00_ContentPlaceHolder1_ContentPlaceHolder1__ButtonSearch"


def pause(page, seconds=3):
    page.wait_for_timeout(seconds * 1000)


def main() -> int:
    out = Path("map-control-probe")
    out.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=False, slow_mo=50)
        page = browser.new_page(viewport={"width": 3840, "height": 2160}, device_scale_factor=1)
        page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=60_000)
        pause(page)
        page.fill(PARCEL_INPUT, PARCEL)
        page.click(SEARCH_BUTTON)
        page.wait_for_load_state("domcontentloaded", timeout=60_000)
        pause(page)
        result = page.locator("[id*='GridViewResults'] a").first
        result.click()
        page.wait_for_load_state("domcontentloaded", timeout=60_000)
        pause(page)
        link = page.get_by_role("link", name=re.compile("view map", re.I))
        if not link.count():
            link = page.locator("a").filter(has_text="Map").first
        try:
            with page.expect_popup(timeout=5_000) as popup:
                link.click()
            map_page = popup.value
        except PlaywrightTimeoutError:
            link.click()
            map_page = page
        map_page.wait_for_load_state("domcontentloaded", timeout=60_000)
        pause(map_page, 6)
        map_page.screenshot(path=str(out / "map.png"), full_page=False)
        controls = map_page.locator("button, a, div[role='button'], [title], [aria-label]").evaluate_all(
            """els => els.map((e, i) => ({
                i,
                tag: e.tagName,
                role: e.getAttribute('role'),
                text: (e.innerText || e.value || '').trim().slice(0, 80),
                title: e.getAttribute('title'),
                aria: e.getAttribute('aria-label'),
                id: e.id || null,
                classes: typeof e.className === 'string' ? e.className.slice(0, 120) : null,
                rect: (() => { const r = e.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height}; })()
            })).filter(x => x.text || x.title || x.aria || x.role === 'button')"""
        )
        (out / "controls.json").write_text(json.dumps(controls, indent=2), encoding="utf-8")
        print(json.dumps(controls[:120], indent=2))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
