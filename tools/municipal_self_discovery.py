from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SECTION_CACHE_ROOT = PROJECT_ROOT / "cache" / "municipal-sections"
BOT_CACHE_ROOT = PROJECT_ROOT / "cache" / "municipal-bots"
SOURCE_STATUS_ROOT = PROJECT_ROOT / "cache" / "municipal-source-status"
REPORT_ROOT = PROJECT_ROOT / "wiki" / "municipal-self-discovery"
QUEUE_PATH = PROJECT_ROOT / "cache" / "municipal-self-discovery" / "ingestion_queue.json"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from parcel_packet.municipal_bots import MUNICIPAL_BOTS, build_municipal_profile


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit every PropSpector municipal bot for cache-backed interpretation readiness.")
    parser.add_argument("--no-write", action="store_true", help="Print report only; do not update wiki/cache files.")
    args = parser.parse_args()

    rows = [_audit_profile(profile) for profile in MUNICIPAL_BOTS]
    report = _render_report(rows)
    if args.no_write:
        print(report)
        return 0

    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now().date().isoformat()
    (REPORT_ROOT / "latest.md").write_text(report, encoding="utf-8")
    (REPORT_ROOT / f"{today}.md").write_text(report, encoding="utf-8")
    QUEUE_PATH.write_text(json.dumps([row for row in rows if row["queue_reason"]], indent=2), encoding="utf-8")
    print(f"Wrote {REPORT_ROOT / 'latest.md'}")
    print(f"Wrote {QUEUE_PATH}")
    return 0


def _audit_profile(profile) -> dict[str, object]:
    sections = _section_cache(profile.key)
    learning = _learning_cache(profile.key)
    source_status = _source_status_cache(profile.key)
    sample_zoning = _sample_zoning_line(profile, sections)
    interpreted = build_municipal_profile(profile.key, 1.0, (sample_zoning,) if sample_zoning else (), (), 1)
    statuses = [item.status for item in interpreted.recommendations]
    placeholder_risk = any(status in {"Further Code Review Required", "Next Interpreter Required"} for status in statuses)
    has_cache = bool(sections)
    has_answer = any(
        status
        in {
            "Cached Code Interpreter Active",
            "District Cache Match",
            "Cached Use Answer",
            "Cached Permission Signals",
            "Preliminary Municipal Yield",
            "Preliminary Municipal Screen",
            "District Use Answer",
            "Board Review Path",
            "Use Translator Active",
        }
        for status in statuses
    )
    queue_reason = ""
    if not has_cache:
        queue_reason = "Needs rendered ordinance section cache"
    elif not has_answer:
        queue_reason = "Cache exists but interpreter produced no source-backed answer cards"
    elif placeholder_risk:
        queue_reason = "Interpreter still exposes generic placeholder-style status"

    return {
        "key": profile.key,
        "display_name": profile.display_name,
        "code_home": profile.code_home,
        "section_count": len(sections),
        "usable_cache": has_cache,
        "learning_status": _learning_status_label(learning, source_status),
        "dependency_coverage": learning.get("dependency_coverage") or {},
        "sample_zoning": sample_zoning,
        "recommendation_statuses": statuses,
        "source_backed_answers": has_answer,
        "placeholder_risk": placeholder_risk,
        "queue_reason": queue_reason,
    }


def _section_cache(key: str) -> list[dict[str, object]]:
    path = SECTION_CACHE_ROOT / key.lower().replace(" ", "_") / "latest.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict) and len(str(item.get("text") or "")) >= 80]


def _learning_cache(key: str) -> dict[str, object]:
    path = BOT_CACHE_ROOT / _safe_name(key) / "latest.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _source_status_cache(key: str) -> dict[str, object]:
    path = SOURCE_STATUS_ROOT / f"{key.lower().replace(' ', '_')}.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _learning_status_label(learning: dict[str, object], source_status: dict[str, object]) -> str:
    status = str(source_status.get("status") or "")
    if status == "pdf_sections_extracted":
        return "Official PDF source extracted into section cache"
    if status == "pdf_sections_available_existing":
        return "Official PDF source cached; existing extracted sections available"
    if status in {"sections_extracted", "sections_merged"}:
        return "Rendered source extracted into section cache"
    return str(learning.get("learn_status") or "No learning cache")


def _sample_zoning_line(profile, sections: list[dict[str, object]]) -> str:
    for preferred in ("C-2", "R-5-C", "R-5-B", "R-3", "R-1-B"):
        district = profile.known_districts.get(preferred)
        if district:
            return f"Municipal zoning district: {preferred} ({district.label})."
    for section in sections:
        title = str(section.get("title") or section.get("query") or "")
        code = _code_from_title(title)
        if code:
            return f"Municipal zoning district: {code} ({title})."
    if profile.known_districts:
        code, district = next(iter(profile.known_districts.items()))
        return f"Municipal zoning district: {code} ({district.label})."
    return "Municipal zoning district: UNKNOWN (unmapped)."


def _code_from_title(title: str) -> str:
    match = None
    for pattern in (
        r"\b([A-Z]{1,3}-\d(?:-[A-Z])?(?:-\d)?)\b",
        r"\b([A-Z]{1,3}\d[A-Z]?)\b",
        r"\b([A-Z]{1,4})\s+district\b",
    ):
        match = re.search(pattern, title.upper())
        if match:
            return match.group(1)
    return ""


def _render_report(rows: list[dict[str, object]]) -> str:
    lines = [
        f"# Municipal Self-Discovery Audit - {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Purpose",
        "",
        "This audit enforces the PropSpector rule that every municipal bot must seek source material, cache it, read it, interpret it, and avoid generic placeholder cards wherever cached code can answer the question.",
        "",
        "## Coverage",
        "",
        "| Bot | Sections | Learning Status | Source-Backed Answers | Queue Reason |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {_escape(str(row['display_name']))} | {row['section_count']} | {_escape(str(row['learning_status']))} | {'Yes' if row['source_backed_answers'] else 'No'} | {_escape(str(row['queue_reason']) or '-')} |"
        )
    lines.extend(["", "## Ingestion Queue", ""])
    queued = [row for row in rows if row["queue_reason"]]
    if not queued:
        lines.append("- No municipalities are currently queued.")
    else:
        for row in queued:
            lines.append(f"- **{row['display_name']}**: {row['queue_reason']}; source: {row['code_home'] or 'source discovery needed'}")
    lines.extend(["", "## Details", ""])
    for row in rows:
        coverage = row.get("dependency_coverage") or {}
        coverage_text = ", ".join(f"{key}:{value}" for key, value in coverage.items()) if isinstance(coverage, dict) and coverage else "-"
        statuses = ", ".join(str(status) for status in row["recommendation_statuses"][:8]) or "-"
        lines.extend(
            [
                f"### {row['display_name']}",
                "",
                f"- **Code home**: {row['code_home'] or '-'}",
                f"- **Cached sections**: {row['section_count']}",
                f"- **Learning status**: {row['learning_status']}",
                f"- **Dependency coverage**: {coverage_text}",
                f"- **Sample zoning**: {row['sample_zoning'] or '-'}",
                f"- **Recommendation statuses**: {statuses}",
                f"- **Queue reason**: {row['queue_reason'] or '-'}",
                "",
            ]
        )
    return "\n".join(lines)


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "UNKNOWN"


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
