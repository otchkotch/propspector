from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import urllib.request
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SECTION_ROOT = ROOT / "cache" / "municipal-sections"
SOURCE_ROOT = ROOT / "cache" / "municipal-source-status"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parcel_packet.municipal_bots import MUNICIPAL_BOTS


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
    parser = argparse.ArgumentParser(description="Build rendered ordinance caches for all registered municipal bots.")
    parser.add_argument("--municipality", action="append", help="Optional bot key/name filter. Can be passed more than once.")
    parser.add_argument("--replace", action="store_true", help="Replace each section cache instead of merging.")
    parser.add_argument("--query-limit", type=int, default=0, help="Limit discovery queries per municipality; 0 means full query set.")
    args = parser.parse_args()

    filters = {_normalize_filter(item) for item in args.municipality or []}
    profiles = [profile for profile in MUNICIPAL_BOTS if not filters or _normalize_filter(profile.key) in filters or _normalize_filter(profile.display_name) in filters]
    queries = list(DEFAULT_DISCOVERY_QUERIES[: args.query_limit or None])

    SECTION_ROOT.mkdir(parents=True, exist_ok=True)
    SOURCE_ROOT.mkdir(parents=True, exist_ok=True)

    summary: list[dict[str, object]] = []
    browser = None
    page = None
    for profile in profiles:
        print(f"\n=== {profile.display_name} ===", flush=True)
        if _needs_browser(profile):
            if browser is None or page is None:
                from playwright.sync_api import sync_playwright

                playwright = sync_playwright().start()
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1400, "height": 1000})
        row = _build_profile_cache(page, profile, queries, replace=args.replace)
        summary.append(row)
    if browser is not None:
        browser.close()

    output = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "municipality_count": len(summary),
        "results": summary,
    }
    (SOURCE_ROOT / "latest-build.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"\nWrote {SOURCE_ROOT / 'latest-build.json'}")
    success_statuses = {"sections_extracted", "sections_merged", "pdf_sections_extracted", "pdf_sections_available_existing"}
    return 1 if any(item.get("status") not in success_statuses for item in summary) else 0


def _build_profile_cache(page, profile, queries: list[str], replace: bool) -> dict[str, object]:
    status: dict[str, object] = {
        "key": profile.key,
        "display_name": profile.display_name,
        "source_url": profile.code_home,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "status": "not_checked",
        "section_count": 0,
        "notes": [],
    }
    if not profile.code_home:
        status["status"] = "missing_source_url"
        return _write_status(profile.key, status)
    parsed = urlparse(profile.code_home)
    if parsed.path.lower().endswith(".pdf"):
        return _build_pdf_profile_cache(profile, replace=replace, status=status)
    if "municode.com" not in parsed.netloc.lower():
        status["status"] = "non_municode_source_pending_extractor"
        status["notes"] = ["The municipal registry points to a non-Municode source. A source-specific extractor is required."]
        return _write_status(profile.key, status)
    if page is None:
        status["status"] = "browser_dependency_missing"
        status["notes"] = ["A browser runtime is required for rendered Municode extraction."]
        return _write_status(profile.key, status)

    base_url = profile.code_home.split("?", 1)[0]
    try:
        page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(8_000)
    except Exception as exc:
        status["status"] = "source_load_failed"
        status["notes"] = [f"{type(exc).__name__}: {exc}"]
        return _write_status(profile.key, status)

    if not _is_valid_municode_code_page(page, profile):
        status["status"] = "municode_source_invalid_or_state_landing"
        status["notes"] = [
            f"Rendered URL: {page.url}",
            f"Rendered title: {page.title()}",
            "The registry source does not expose a municipal code page for this bot.",
        ]
        _write_sections(profile.key, [], replace=True)
        return _write_status(profile.key, status)

    from tools.extract_municode_sections import _extract_query

    extracted = []
    for query in queries:
        try:
            result = _extract_query(page, query)
        except Exception as exc:
            print(f"- {query}: skipped ({type(exc).__name__})", flush=True)
            continue
        if result and len(result.text) >= 80:
            extracted.append(result)
            print(f"- {query}: {result.title} ({len(result.text)} chars)", flush=True)
        else:
            print(f"- {query}: no section", flush=True)

    merged = _write_sections(profile.key, [asdict(item) for item in extracted], replace=replace)
    status["status"] = "sections_extracted" if replace else "sections_merged"
    status["section_count"] = len(merged)
    if not merged:
        status["status"] = "no_sections_extracted"
        status["notes"] = ["The source page loaded but no usable rendered sections were extracted."]
    return _write_status(profile.key, status)


def _needs_browser(profile) -> bool:
    parsed = urlparse(profile.code_home or "")
    return "municode.com" in parsed.netloc.lower() and not parsed.path.lower().endswith(".pdf")


def _build_pdf_profile_cache(profile, replace: bool, status: dict[str, object]) -> dict[str, object]:
    document_dir = ROOT / "cache" / "municipal-source-documents" / profile.key.lower().replace(" ", "_")
    document_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = document_dir / "zoning-code.pdf"
    try:
        request = urllib.request.Request(profile.code_home, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            pdf_path.write_bytes(response.read())
    except Exception as exc:
        status["status"] = "pdf_source_download_failed"
        status["notes"] = [f"{type(exc).__name__}: {exc}"]
        return _write_status(profile.key, status)

    try:
        from tools.extract_pdf_code_sections import _read_pdf, _split_sections
    except Exception as exc:
        existing = _existing_sections(profile.key)
        if existing:
            status["status"] = "pdf_sections_available_existing"
            status["section_count"] = len(existing)
            status["notes"] = [
                "PDF extraction dependency is not available in this Python environment, but an existing PDF-derived section cache is present.",
                f"{type(exc).__name__}: {exc}",
            ]
            return _write_status(profile.key, status)
        status["status"] = "pdf_extractor_dependency_missing"
        status["notes"] = [
            f"{type(exc).__name__}: {exc}",
            "Run tools/extract_pdf_code_sections.py with the bundled PDF-capable Python runtime or install pdfplumber in the project environment.",
        ]
        return _write_status(profile.key, status)

    try:
        text = _read_pdf(pdf_path)
        sections = [asdict(section) for section in _split_sections(text, profile.code_home)]
    except Exception as exc:
        status["status"] = "pdf_section_extraction_failed"
        status["notes"] = [f"{type(exc).__name__}: {exc}"]
        return _write_status(profile.key, status)

    merged = _write_sections(profile.key, sections, replace=replace)
    status["status"] = "pdf_sections_extracted"
    status["section_count"] = len(merged)
    status["notes"] = [f"Downloaded source PDF to {pdf_path}"]
    if not merged:
        status["status"] = "no_sections_extracted"
        status["notes"].append("PDF downloaded but no usable code sections were extracted.")
    return _write_status(profile.key, status)


def _existing_sections(key: str) -> list[dict[str, str]]:
    path = SECTION_ROOT / key.lower().replace(" ", "_") / "latest.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in data if isinstance(item, dict) and len(str(item.get("text") or "")) >= 80] if isinstance(data, list) else []


def _is_valid_municode_code_page(page, profile) -> bool:
    rendered_url = page.url.lower()
    title = page.title().lower()
    body = page.locator("body").inner_text(timeout=10_000).lower()
    if rendered_url.rstrip("/") in {"https://library.municode.com/de", "https://library.municode.com/de/"}:
        return False
    if title.startswith("delaware | municode library"):
        return False
    return "code of ordinances" in body or "chapter" in body or profile.display_name.lower().split()[-1] in body


def _write_sections(key: str, sections: list[dict[str, str]], replace: bool) -> list[dict[str, str]]:
    out_dir = SECTION_ROOT / key.lower().replace(" ", "_")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "latest.json"
    existing = _existing_sections(key)
    if replace and existing and len(sections) < len(existing):
        print(f"preserved existing stronger cache for {key}: existing={len(existing)} new={len(sections)}", flush=True)
        return existing
    merged = sections
    if out_path.exists() and not replace:
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = []
        by_query: dict[str, dict[str, str]] = {}
        for item in existing if isinstance(existing, list) else []:
            if isinstance(item, dict):
                by_query[str(item.get("query") or item.get("title") or len(by_query))] = item
        for item in sections:
            by_query[str(item.get("query") or item.get("title") or len(by_query))] = item
        merged = list(by_query.values())
    out_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return merged


def _write_status(key: str, status: dict[str, object]) -> dict[str, object]:
    path = SOURCE_ROOT / f"{key.lower().replace(' ', '_')}.json"
    path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    print(f"{status['status']} | sections={status.get('section_count', 0)}", flush=True)
    return status


def _normalize_filter(value: str) -> str:
    return " ".join(value.upper().replace("_", " ").split())


if __name__ == "__main__":
    raise SystemExit(main())
