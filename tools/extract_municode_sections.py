from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "cache" / "municipal-sections"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parcel_packet.municipal_bots import MUNICIPAL_BOTS


@dataclass(frozen=True)
class ExtractedSection:
    query: str
    title: str
    url: str
    extracted_at: str
    text: str


MUNICIPAL_URLS = {
    profile.key.lower().replace(" ", "_"): profile.code_home.split("?", 1)[0]
    for profile in MUNICIPAL_BOTS
    if profile.code_home
}

DEFAULT_DISCOVERY_QUERIES = (
    "zoning districts",
    "district regulations",
    "residential districts",
    "commercial districts",
    "business districts",
    "office districts",
    "institutional districts",
    "civic districts",
    "public districts",
    "industrial districts",
    "manufacturing districts",
    "waterfront districts",
    "mixed use districts",
    "mixed-use districts",
    "planned districts",
    "overlay districts",
    "conservation districts",
    "permitted uses",
    "uses permitted",
    "conditional uses",
    "special uses",
    "limited uses",
    "special exceptions",
    "definitions",
    "area bulk",
    "density",
    "floor area ratio",
    "height",
    "setback",
    "yard",
    "lot area",
    "parking",
    "loading",
    "street frontage",
    "access",
    "subdivision",
    "stormwater",
    "floodplain",
    "historic district",
    "site plan",
    "board of adjustment",
    "variance",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract public Municode sections through a rendered browser session.")
    parser.add_argument("municipality", choices=sorted(MUNICIPAL_URLS))
    parser.add_argument("queries", nargs="*", help="Section or topic searches. Omit to run the default zoning discovery set.")
    parser.add_argument("--replace", action="store_true", help="Replace the municipality cache instead of merging into it.")
    args = parser.parse_args()
    queries = args.queries or list(DEFAULT_DISCOVERY_QUERIES)

    extracted: list[ExtractedSection] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.goto(MUNICIPAL_URLS[args.municipality], wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(7_000)
        for query in queries:
            try:
                result = _extract_query(page, query)
                if result:
                    extracted.append(result)
            except Exception as exc:
                print(f"- {query}: skipped ({exc.__class__.__name__})")
        browser.close()

    out_dir = OUT_ROOT / args.municipality
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "latest.json"
    merged = [asdict(item) for item in extracted]
    if out_path.exists() and not args.replace:
        merged = _merge_existing(out_path, merged)
    out_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")
    for item in merged:
        print(f"- {item.get('query')}: {item.get('title')} ({len(str(item.get('text') or ''))} chars)")
    return 0


def _merge_existing(path: Path, new_items: list[dict[str, str]]) -> list[dict[str, str]]:
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        existing = []
    merged_by_query: dict[str, dict[str, str]] = {}
    for item in existing if isinstance(existing, list) else []:
        if isinstance(item, dict):
            merged_by_query[str(item.get("query") or item.get("title") or len(merged_by_query))] = item
    for item in new_items:
        merged_by_query[str(item.get("query") or item.get("title") or len(merged_by_query))] = item
    return list(merged_by_query.values())


def _extract_query(page, query: str) -> ExtractedSection | None:
    search = _search_box(page)
    if search is None:
        return None
    search.fill(query)
    search.press("Enter")
    page.wait_for_timeout(5_000)
    links = page.locator("a").evaluate_all(
        """(els, query) => els.map((e, i) => ({
            i,
            text: e.innerText || "",
            href: e.href || ""
        })).filter(x => x.text.toLowerCase().includes(query.toLowerCase()) || x.href.toLowerCase().includes(query.toLowerCase().replaceAll(" ", "")))""",
        query,
    )
    if not links:
        return None
    page.locator("a").nth(int(links[0]["i"])).click()
    page.wait_for_timeout(7_000)
    title = str(links[0]["text"]).strip()
    text = _active_chunk_text(page, page.url) or _section_text(page.locator("body").inner_text(timeout=10_000), title)
    return ExtractedSection(
        query=query,
        title=title,
        url=page.url,
        extracted_at=datetime.now().isoformat(timespec="seconds"),
        text=text,
    )


def _search_box(page):
    selectors = (
        'input[placeholder*="Search or jump"]',
        'input[placeholder*="Search"]',
        'input[type="search"]',
        'input[aria-label*="Search"]',
    )
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count():
                locator.wait_for(state="visible", timeout=5_000)
                return locator
        except Exception:
            continue
    return None


def _active_chunk_text(page, url: str) -> str:
    match = re.search(r"nodeId=([^&#]+)", url)
    if not match:
        return ""
    chunk_id = "c_" + match.group(1)
    locator = page.locator(f'[id="{chunk_id}"].chunk')
    if not locator.count():
        locator = page.locator(f'[id="{chunk_id}"]')
    if not locator.count():
        return ""
    return _trim_noise(locator.first.inner_text(timeout=10_000))


def _section_text(body: str, title: str) -> str:
    normalized = "\n".join(line.rstrip() for line in body.splitlines())
    heading = _clean_heading(title)
    start = _find_heading(normalized, heading)
    if start < 0:
        return _trim_noise(normalized)
    next_heading = re.search(r"\nSec(?:s)?\. 48-\d+[^\\n]*", normalized[start + len(heading) :])
    end = start + len(heading) + next_heading.start() if next_heading else len(normalized)
    return _trim_noise(normalized[start:end])


def _find_heading(text: str, heading: str) -> int:
    candidates = [heading, heading.replace(" - ", " -"), heading.replace(" -", " - ")]
    for candidate in candidates:
        index = text.find(candidate)
        if index >= 0:
            return index
    return -1


def _clean_heading(value: str) -> str:
    return " ".join(value.split())


def _trim_noise(value: str) -> str:
    lines = [line.strip() for line in value.splitlines()]
    keep: list[str] = []
    skip_tokens = {
        "SHARE LINK TO SECTION",
        "PRINT SECTION",
        "DOWNLOAD (DOCX) OF SECTIONS",
        "EMAIL SECTION",
        "COMPARE VERSIONS",
        "SHOW CHANGES",
        "MORE",
    }
    for line in lines:
        if not line or line in skip_tokens:
            continue
        keep.append(line)
    return "\n".join(keep).strip()


if __name__ == "__main__":
    raise SystemExit(main())
