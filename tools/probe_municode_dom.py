from __future__ import annotations

from playwright.sync_api import sync_playwright


URL = "https://library.municode.com/de/wilmington/codes/code_of_ordinances?nodeId=PTIIWICO_CH48ZO_ARTIVREDI_DIV2USRE_S48-139CDI"


def main() -> int:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(10_000)
        elements = page.locator("body *").evaluate_all(
            """els => els.map((e, i) => ({
                i,
                tag: e.tagName,
                cls: String(e.className || ""),
                id: e.id || "",
                text: (e.innerText || "").slice(0, 500)
            })).filter(x => x.text.includes("Sec. 48-139") || x.text.includes("Any use permitted"))"""
        )
        print(len(elements))
        for item in elements[:120]:
            print(item)
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
