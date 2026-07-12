from __future__ import annotations

from playwright.sync_api import sync_playwright


URL = "https://library.municode.com/de/wilmington/codes/code_of_ordinances"


def main() -> int:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(8_000)
        print("url", page.url)
        print("title", page.title())
        inputs = page.locator("input").evaluate_all(
            """els => els.map((e, i) => ({
                i,
                placeholder: e.getAttribute("placeholder"),
                aria: e.getAttribute("aria-label"),
                type: e.getAttribute("type"),
                cls: e.className
            }))"""
        )
        print("inputs", inputs)
        buttons = page.locator("button").evaluate_all(
            """els => els.slice(0, 30).map((e, i) => ({
                i,
                text: e.innerText,
                aria: e.getAttribute("aria-label"),
                title: e.getAttribute("title"),
                cls: e.className
            }))"""
        )
        print("buttons", buttons)
        text = page.locator("body").inner_text(timeout=5_000)
        print(text[:5_000].encode("ascii", "replace").decode("ascii"))
        for term in ("Sec. 48-139",):
            print("\nSEARCH", term)
            search = page.get_by_placeholder("Search or jump to")
            search.fill(term)
            search.press("Enter")
            page.wait_for_timeout(6_000)
            body = page.locator("body").inner_text(timeout=5_000)
            print(body[:8_000].encode("ascii", "replace").decode("ascii"))
            links = page.locator("a").evaluate_all(
                """els => els.map((e, i) => ({
                    i,
                    text: e.innerText,
                    href: e.href,
                    cls: e.className
                })).filter(x => x.text && x.text.includes("48-139"))"""
            )
            print("links", links)
            if links:
                page.locator("a", has_text="Sec. 48-139").first.click()
                page.wait_for_timeout(8_000)
                content = page.locator("body").inner_text(timeout=5_000)
                print("\nCLICKED RESULT")
                print("url", page.url)
                print(content[:12_000].encode("ascii", "replace").decode("ascii"))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
