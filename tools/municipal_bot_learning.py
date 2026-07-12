from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import html
import json
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEARNING_ROOT = PROJECT_ROOT / "wiki" / "municipal-learning"
CACHE_ROOT = PROJECT_ROOT / "cache" / "municipal-bots"
SECTION_CACHE_ROOT = PROJECT_ROOT / "cache" / "municipal-sections"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from parcel_packet.municipal_bots import MUNICIPAL_BOTS, MunicipalBotProfile


USER_AGENT = "PropSpector municipal learning cache; low-frequency source check"
KEY_TERMS: tuple[str, ...] = (
    "zoning",
    "subdivision",
    "parking",
    "setback",
    "density",
    "height",
    "use",
    "utilities",
    "stormwater",
    "fire",
    "streets",
    "historic",
    "fees",
)
DEPENDENCY_TERMS: dict[str, tuple[str, ...]] = {
    "district_inventory": ("district", "districts", "district regulations", "zoning districts", "classification"),
    "commercial_institutional_districts": (
        "commercial",
        "office",
        "business",
        "institutional",
        "civic",
        "public",
        "industrial",
        "manufacturing",
        "waterfront",
        "mixed use",
        "mixed-use",
        "planned",
    ),
    "use_permissions": ("permitted use", "principal use", "use table", "permitted uses", "uses permitted"),
    "limited_special_conditions": ("conditional use", "special use", "limited use", "special exception", "board approval"),
    "definitions": ("definition", "definitions", "meaning", "shall mean"),
    "density_bulk": ("density", "floor area", "far", "lot area", "setback", "height", "yard", "coverage"),
    "parking_loading": ("parking", "loading", "driveway", "vehicle"),
    "subdivision": ("subdivision", "land development", "record plan", "minor subdivision", "major subdivision"),
    "streets_access": ("street", "access", "frontage", "right-of-way", "highway", "road"),
    "utilities_fees": ("utility", "sewer", "water", "connection fee", "impact fee", "tap fee"),
    "stormwater_environment": ("stormwater", "floodplain", "wetland", "tree", "forest", "environment"),
    "fire_building": ("fire", "building code", "construction", "sprinkler"),
    "historic_overlays": ("historic", "overlay", "historic district", "design review"),
    "procedure": ("hearing", "board of adjustment", "planning commission", "variance", "appeal", "site plan"),
    "calibration_records": ("record plan", "approved plan", "major plan", "minor plan"),
}
SECTION_RE = re.compile(
    r"\b(?:Sec\.|Section|§)\s*[A-Za-z0-9][A-Za-z0-9.\-–:]*\s*(?:[-–—:]\s*)?[^.;\n]{0,140}",
    re.IGNORECASE,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run low-frequency PropSpector municipal bot learning.")
    parser.add_argument("--delay", type=float, default=0.25, help="Seconds to wait between municipal source checks.")
    parser.add_argument("--only", default="", help="Optional municipal bot key to learn first/by itself, such as WILMINGTON.")
    parser.add_argument("--no-write", action="store_true", help="Print report only; do not update cache/wiki files.")
    args = parser.parse_args()

    results = []
    profiles = list(MUNICIPAL_BOTS)
    if args.only:
        wanted = args.only.upper().strip()
        profiles = [profile for profile in profiles if profile.key.upper() == wanted]
    for index, profile in enumerate(profiles):
        if index:
            time.sleep(max(0.0, args.delay))
        results.append(_learn_profile(profile))

    report = _render_report(results)
    if args.no_write:
        print(report)
        return 0

    LEARNING_ROOT.mkdir(parents=True, exist_ok=True)
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    today = datetime.now().date().isoformat()
    (LEARNING_ROOT / "latest.md").write_text(report, encoding="utf-8")
    (LEARNING_ROOT / f"{today}.md").write_text(report, encoding="utf-8")
    print(f"Wrote {LEARNING_ROOT / 'latest.md'}")
    return 0


def _learn_profile(profile: MunicipalBotProfile) -> dict[str, object]:
    checked_at = datetime.now().isoformat(timespec="seconds")
    result: dict[str, object] = {
        "key": profile.key,
        "display_name": profile.display_name,
        "profile_status": profile.status,
        "code_home": profile.code_home,
        "checked_at": checked_at,
        "source_status": profile.source_status,
        "learn_status": "Not checked",
        "http_status": None,
        "title": "",
        "content_hash": "",
        "signals": {},
        "section_candidates": [],
        "district_candidates": [],
        "permission_signals": {},
        "cached_sections": [],
        "dependency_coverage": {},
        "notes": list(profile.source_notes),
        "next_tasks": list(profile.next_tasks),
    }
    if not profile.code_home:
        result["learn_status"] = "Needs source discovery"
        _write_cache(profile, result)
        return result

    cached_sections = _cached_rendered_sections(profile)
    if cached_sections:
        result["cached_sections"] = cached_sections
        section_candidates = _sections_from_rendered_cache(cached_sections)
        result["section_candidates"] = section_candidates
        result["district_candidates"] = _district_candidates_from_sections(section_candidates)
        result["permission_signals"] = _permission_signals(section_candidates)
        result["dependency_coverage"] = _dependency_coverage(section_candidates)
        result["learn_status"] = "Rendered section cache learned; implementation profile needed"
        result["notes"] = [
            *profile.source_notes,
            "Fast learning used browser-rendered public Municode section chunks cached under cache/municipal-sections. This avoids waiting for broad shell-only scans.",
        ]

    request = urllib.request.Request(profile.code_home, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(750_000)
            status = getattr(response, "status", 200)
            charset = response.headers.get_content_charset() or "utf-8"
        text = raw.decode(charset, errors="replace")
        result["http_status"] = status
        if not cached_sections:
            result["learn_status"] = "Source reachable"
        result["title"] = _title(text)
        result["content_hash"] = hashlib.sha256(raw).hexdigest()
        result["signals"] = _signals(text)
        visible = _visible_text(text)
        sections = list(result.get("section_candidates") or []) or _section_candidates(visible)
        result["section_candidates"] = sections
        result["district_candidates"] = _district_candidates_from_sections(sections)
        result["permission_signals"] = _permission_signals(sections)
        result["dependency_coverage"] = _dependency_coverage(sections)
        if not cached_sections:
            result["learn_status"] = _learn_status_from_sections(sections)
        if _looks_like_municode_shell(text, sections):
            result["learn_status"] = "Municode shell reachable; ordinance content not exposed in page HTML"
            result["notes"] = [
                *profile.source_notes,
                "The public Municode shell loaded, but ordinance sections were not present in the returned HTML. The bot needs an approved content endpoint, exported source snapshot, or manually seeded section map before parcel-specific municipal yield math can be trusted.",
            ]
    except urllib.error.HTTPError as exc:
        result["http_status"] = exc.code
        if exc.code in {401, 403, 429}:
            result["learn_status"] = "Source blocks scripted cache check"
            result["notes"] = [*profile.source_notes, "Learning paused for this source until an approved access method or manual source snapshot is provided."]
        else:
            result["learn_status"] = f"HTTP error {exc.code}"
    except Exception as exc:
        result["learn_status"] = f"Learning error: {exc.__class__.__name__}"
        result["notes"] = [*profile.source_notes, str(exc)]

    _write_cache(profile, result)
    return result


def _write_cache(profile: MunicipalBotProfile, result: dict[str, object]) -> None:
    folder = CACHE_ROOT / _safe_name(profile.key)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "latest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


def _cached_rendered_sections(profile: MunicipalBotProfile) -> list[dict[str, object]]:
    folder = SECTION_CACHE_ROOT / profile.key.lower().replace(" ", "_")
    path = folder / "latest.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _sections_from_rendered_cache(cached_sections: list[dict[str, object]]) -> list[dict[str, object]]:
    sections: list[dict[str, object]] = []
    for item in cached_sections:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "")
        title = str(item.get("title") or item.get("query") or "Cached section")
        categories = _categories_for(text)
        if not categories:
            categories = ["zoning"]
        sections.append(
            {
                "heading": _trim(title, 160),
                "categories": categories,
                "context": _trim(text, 520),
            }
        )
    return sections


def _signals(text: str) -> dict[str, int]:
    lowered = _visible_text(text).lower()
    return {term: lowered.count(term) for term in KEY_TERMS if lowered.count(term)}


def _section_candidates(text: str) -> list[dict[str, object]]:
    normalized = " ".join(html.unescape(text).split())
    candidates: list[dict[str, object]] = []
    seen: set[str] = set()
    for match in SECTION_RE.finditer(normalized):
        start = max(0, match.start() - 220)
        end = min(len(normalized), match.end() + 260)
        heading = _trim(match.group(0), 160)
        context = normalized[start:end]
        categories = _categories_for(context)
        if not categories:
            continue
        key = heading.lower()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            {
                "heading": heading,
                "categories": categories,
                "context": _trim(context, 520),
            }
        )
        if len(candidates) >= 80:
            break
    return candidates


def _dependency_coverage(sections: list[dict[str, object]]) -> dict[str, int]:
    coverage = {category: 0 for category in DEPENDENCY_TERMS}
    for section in sections:
        for category in section.get("categories") or ():
            if category in coverage:
                coverage[category] += 1
    return {category: count for category, count in coverage.items() if count}


def _learn_status_from_sections(sections: list[dict[str, object]]) -> str:
    coverage = _dependency_coverage(sections)
    core = {
        "district_inventory",
        "use_permissions",
        "limited_special_conditions",
        "density_bulk",
        "parking_loading",
        "streets_access",
        "procedure",
    }
    if core <= set(coverage):
        return "Municipal ecosystem map learned; implementation profile needed"
    if sections:
        return "Partial section map learned"
    return "Source reachable; section map not detected"


def _district_candidates_from_sections(sections: list[dict[str, object]]) -> list[str]:
    found: set[str] = set()
    for section in sections:
        text = " ".join(str(section.get(key) or "") for key in ("heading", "context"))
        for match in re.finditer(r"\b(?:[A-Z]{1,3}-?\d+[A-Z]?|R-\d(?:-[A-Z])?|C-\d|M-\d|W-\d)\b", text.upper()):
            value = match.group(0)
            if len(value) <= 8:
                found.add(value)
    return sorted(found)


def _permission_signals(sections: list[dict[str, object]]) -> dict[str, int]:
    buckets = {
        "by_right": ("permitted", "principal use", "uses permitted", "permitted uses"),
        "limited": ("limited use",),
        "special": ("special use", "special exception"),
        "conditional": ("conditional use",),
        "prohibited": ("prohibited", "not permitted"),
    }
    text = "\n".join(
        " ".join(str(section.get(key) or "") for key in ("heading", "context"))
        for section in sections
    ).lower()
    return {
        bucket: sum(text.count(term) for term in terms)
        for bucket, terms in buckets.items()
        if sum(text.count(term) for term in terms)
    }


def _looks_like_municode_shell(text: str, sections: list[dict[str, object]]) -> bool:
    if sections:
        return False
    lowered = text.lower()
    return "municode library" in lowered and "serverprops" in lowered and "codescontent" not in lowered


def _categories_for(text: str) -> list[str]:
    lowered = text.lower()
    return [category for category, terms in DEPENDENCY_TERMS.items() if any(term in lowered for term in terms)]


def _trim(value: str, limit: int) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "..."


def _visible_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return " ".join(text.split())


def _title(html: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    if not match:
        return ""
    return " ".join(re.sub(r"<[^>]+>", " ", match.group(1)).split())


def _render_report(results: list[dict[str, object]]) -> str:
    lines = [
        f"# Municipal Bot Learning Pass - {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Journal Priority",
        "",
        "This pass exists because the personal journal says municipal bots should learn continuously throughout the day, cache/read source material quickly, and avoid issuing confident yields until related code dependencies are understood.",
        "",
        "Learning is source-respecting and low-frequency. If a source blocks scripted access, PropSpector records the obstacle instead of trying to bypass it.",
        "",
        "## Bot Results",
        "",
        "| Bot | Profile | Learning Status | Source | Dependency Coverage | Next Need |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for result in results:
        coverage = result.get("dependency_coverage") or {}
        coverage_text = ", ".join(f"{key}:{value}" for key, value in coverage.items()) if isinstance(coverage, dict) and coverage else "-"
        districts = result.get("district_candidates") or []
        district_text = ", ".join(str(item) for item in districts[:12]) if isinstance(districts, list) and districts else "-"
        next_tasks = result.get("next_tasks") or []
        next_need = str(next_tasks[0]) if isinstance(next_tasks, list) and next_tasks else "-"
        source = str(result.get("code_home") or "-")
        lines.append(
            f"| {_escape(str(result['display_name']))} | {_escape(str(result['profile_status']))} | {_escape(str(result['learn_status']))} | {_escape(source)} | {_escape(coverage_text + '; districts: ' + district_text)} | {_escape(next_need)} |"
        )
    lines.extend(["", "## Details", ""])
    for result in results:
        lines.extend(
            [
                f"### {result['display_name']}",
                "",
                f"- **Checked**: {result['checked_at']}",
                f"- **Profile status**: {result['profile_status']}",
                f"- **Learning status**: {result['learn_status']}",
                f"- **HTTP status**: {result['http_status'] or '-'}",
                f"- **Title**: {result['title'] or '-'}",
                f"- **Content hash**: {result['content_hash'] or '-'}",
                f"- **Source status**: {result['source_status']}",
                "",
                "**Dependency Coverage**",
                "",
            ]
        )
        coverage = result.get("dependency_coverage") or {}
        if isinstance(coverage, dict) and coverage:
            for category, count in coverage.items():
                lines.append(f"- {category}: {count} candidate sections")
        else:
            lines.append("- No dependency sections detected in this pass.")
        districts = result.get("district_candidates") or []
        permission_signals = result.get("permission_signals") or {}
        lines.extend(["", "**District / Permission Signals**", ""])
        lines.append("- District candidates: " + (", ".join(str(item) for item in districts) if isinstance(districts, list) and districts else "none detected"))
        if isinstance(permission_signals, dict) and permission_signals:
            lines.append("- Permission signals: " + ", ".join(f"{key}: {value}" for key, value in permission_signals.items()))
        else:
            lines.append("- Permission signals: none detected")
        lines.extend(["", "**Section Candidates**", ""])
        sections = result.get("section_candidates") or []
        if isinstance(sections, list) and sections:
            for section in sections[:20]:
                categories = ", ".join(section.get("categories") or ())
                lines.append(f"- **{section.get('heading', '-')}** ({categories}): {section.get('context', '-')}")
        else:
            lines.append("- No section candidates cached.")
        lines.extend(
            [
                "",
                "**Notes**",
                "",
            ]
        )
        for note in result.get("notes") or []:
            lines.append(f"- {note}")
        lines.extend(["", "**Next Tasks**", ""])
        for task in result.get("next_tasks") or []:
            lines.append(f"- {task}")
        lines.append("")
    return "\n".join(lines)


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "UNKNOWN"


if __name__ == "__main__":
    raise SystemExit(main())
