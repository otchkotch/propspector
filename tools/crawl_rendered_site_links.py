from __future__ import annotations

import argparse
from collections import deque
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright


KEYWORDS = (
    "code",
    "ordinance",
    "zoning",
    "planning",
    "subdivision",
    "land use",
    "development",
    "ecode",
    "municode",
    "pdf",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Crawl rendered links on a municipal site.")
    parser.add_argument("url")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--wait-ms", type=int, default=1200)
    parser.add_argument("--timeout-ms", type=int, default=12_000)
    args = parser.parse_args()
    root_host = urlparse(args.url).netloc.lower()
    seen: set[str] = set()
    queue: deque[str] = deque([args.url])
    matches: list[tuple[str, str, str]] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        while queue and len(seen) < args.limit:
            url = queue.popleft()
            if url in seen:
                continue
            seen.add(url)
            print(f"VISIT {len(seen):03d} {url}", flush=True)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=args.timeout_ms)
                page.wait_for_timeout(args.wait_ms)
                text = page.locator("body").inner_text(timeout=args.timeout_ms)
                links = page.locator("a").evaluate_all(
                    """els => els.map(e => ({text:(e.innerText||"").trim(), href:e.href||""}))"""
                )
            except Exception as exc:
                print("SKIP", url, type(exc).__name__)
                continue
            haystack = f"{url}\n{text}".lower()
            if any(keyword in haystack for keyword in KEYWORDS):
                matches.append((url, page.title(), "page"))
            for link in links:
                href = str(link.get("href") or "")
                label = " ".join(str(link.get("text") or "").split())
                if not href:
                    continue
                absolute = urljoin(url, href).split("#", 1)[0]
                parsed = urlparse(absolute)
                if parsed.scheme not in {"http", "https"}:
                    continue
                link_haystack = f"{label}\n{absolute}".lower()
                if any(keyword in link_haystack for keyword in KEYWORDS):
                    matches.append((absolute, label or parsed.path, "link"))
                if parsed.netloc.lower() == root_host and absolute not in seen and len(seen) + len(queue) < args.limit:
                    queue.append(absolute)
        browser.close()

    print(f"Visited {len(seen)} pages")
    for url, label, kind in dict.fromkeys(matches):
        print(f"{kind.upper()} | {label} | {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
