from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re
import sys
import traceback


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WIKI_ROOT = PROJECT_ROOT / "wiki"
DAILY_REVIEW_DIR = WIKI_ROOT / "daily-reviews"
BOT_CACHE_ROOT = PROJECT_ROOT / "cache" / "municipal-bots"
DISCOVERY_CACHE_PATH = PROJECT_ROOT / "cache" / "municipal-discovery" / "latest.json"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from parcel_packet.municipal_bots import MUNICIPAL_BOTS
from parcel_packet.zoning_feasibility_runner import FeasibilityResult, YieldRecommendation, ZoningFeasibilityRunner


@dataclass(frozen=True)
class CalibrationParcel:
    parcel_number: str
    purpose: str
    expected_signal: str


CALIBRATION_PARCELS: tuple[CalibrationParcel, ...] = (
    CalibrationParcel(
        "0804930379",
        "Mixed-use/apartment calibration against known project expectations.",
        "Mixed Use should remain a calculated review-required option near 174 apartments and roughly 25,000 sf commercial GFA.",
    ),
    CalibrationParcel(
        "0902800058",
        "Public-owner/private-market ranking calibration.",
        "Public ownership should produce a private-development caution and avoid ranking civic/custom public uses as the clean private-market answer.",
    ),
    CalibrationParcel(
        "1105400001",
        "Federal-owner detection calibration.",
        "Federal ownership should be recognized and civic/custom public-use buckets should be de-emphasized.",
    ),
    CalibrationParcel(
        "1000100014",
        "Commercial/residential limited-use screening calibration.",
        "Limited-use residential and commercial options should be screened before ranking.",
    ),
    CalibrationParcel(
        "1000100074",
        "CR-style development-option ranking calibration.",
        "Mixed-use, apartment, and commercial options should be compared by planning value, not by hard-coded display order.",
    ),
    CalibrationParcel(
        "1021 Gilpin Avenue",
        "Wilmington address lookup and non-bounded zoning distinction calibration.",
        "Address should resolve to parcel 2602130233; full geometry intersects both R-3 and R-5-C, so Wilmington yield logic must test materiality rather than rely only on representative-point zoning.",
    ),
    CalibrationParcel(
        "2000 Pennsylvania Avenue",
        "Wilmington C-2 inherited residential and mixed-use calibration.",
        "Address should resolve to parcel 2602010008; C-2 should not screen only secondary commercial GFA because Sec. 48-193 imports R-5-C apartment permissions and C-1 commercial uses.",
    ),
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PropSpector daily regulatory interpretation checks.")
    parser.add_argument("parcels", nargs="*", help="Optional parcel numbers. Defaults to the calibration parcel set.")
    parser.add_argument("--no-write", action="store_true", help="Print report only; do not write a wiki file.")
    args = parser.parse_args()

    parcels = _selected_parcels(args.parcels)
    report = _build_report(parcels)

    if args.no_write:
        print(report)
        return 0

    DAILY_REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DAILY_REVIEW_DIR / f"{date.today().isoformat()}.md"
    output_path.write_text(report, encoding="utf-8")
    print(f"Wrote {output_path}")
    return 0


def _selected_parcels(parcel_numbers: list[str]) -> tuple[CalibrationParcel, ...]:
    if not parcel_numbers:
        return CALIBRATION_PARCELS
    by_number = {item.parcel_number: item for item in CALIBRATION_PARCELS}
    selected: list[CalibrationParcel] = []
    for parcel_number in parcel_numbers:
        selected.append(
            by_number.get(
                parcel_number,
                CalibrationParcel(parcel_number, "Ad hoc parcel review.", "No expected signal recorded yet."),
            )
        )
    return tuple(selected)


def _build_report(parcels: tuple[CalibrationParcel, ...]) -> str:
    lines: list[str] = [
        f"# PropSpector Daily Regulatory Review - {date.today().isoformat()}",
        "",
        "## Review Thesis",
        "",
        "The personal journal is the controlling product and interpretation guidance for PropSpector except where the user's direct current instruction says otherwise.",
        "",
        "This review checks whether PropSpector still behaves like a jurisdiction-aware regulatory interpreter: jurisdiction first, uses before math, conservative physical constraints, and visible caveats where the ordinance or GIS facts require human review.",
        "",
        "Journal priority check: new jurisdictions are legal ecosystems until proven otherwise; a zoning chapter is never singularly superior until related direct and indirect code dependencies are checked; bots should learn source material and cache/read it quickly before issuing confident yields.",
        "",
        "## Summary",
        "",
    ]

    results: list[tuple[CalibrationParcel, FeasibilityResult | None, str | None]] = []
    for parcel in parcels:
        try:
            result = ZoningFeasibilityRunner(parcel.parcel_number).analyze()
            results.append((parcel, result, None))
        except Exception:
            results.append((parcel, None, traceback.format_exc()))

    pass_count = sum(1 for _parcel, result, error in results if result is not None and error is None)
    lines.extend(
        [
            f"- Parcels reviewed: {len(results)}",
            f"- Successful runs: {pass_count}",
            f"- Failed runs: {len(results) - pass_count}",
            "",
        ]
    )

    lines.extend(_bot_results_section())
    lines.extend(_discovery_results_section())

    lines.extend(["## Parcel Checks", ""])
    for parcel, result, error in results:
        lines.extend(_parcel_section(parcel, result, error))

    lines.extend(
        [
            "## Architecture Notes",
            "",
            "- Treat missing municipal profiles as review-required, not as county-code fallbacks.",
            "- Keep raw environmental acreage display separate from protected-resource trumping math.",
            "- Use record-plan calibration parcels to identify systematic yield bias.",
            "- Add ordinance-source snapshots before expanding beyond New Castle County so code changes can be detected.",
            "- Treat the personal journal as the governing interpretation thesis unless the user's current direct instruction supersedes it.",
            "",
            "## Next Review Questions",
            "",
            "- Did a source GIS layer or field change?",
            "- Did a known calibration parcel move outside its expected range?",
            "- Did public ownership affect ranking correctly?",
            "- Did any result rely on a limited-use condition that needs a road/access or special-standard check?",
            "- Did the result account for adjoining parcels and practical/legal access to a street, highway, boulevard, alley, or access easement?",
            "- Did the result separate code yield from entitlement risk tied to neighborhood character, civic pressure, or discretionary political approval?",
            "- Is this a municipality-profile issue or a core-engine issue?",
        ]
    )

    return "\n".join(lines) + "\n"


def _bot_results_section() -> list[str]:
    lines = [
        "## Municipal Bot Results",
        "",
        "These results are shown for every registered municipal bot, even when no parcel from that municipality was included in the parcel calibration set.",
        "",
        "| Bot | Profile Status | Learning Status | Last Checked | Source | Next Need |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for profile in MUNICIPAL_BOTS:
        cache = _bot_cache(profile.key)
        learning_status = str(cache.get("learn_status") or "No learning pass recorded yet")
        checked = str(cache.get("checked_at") or "-")
        source = profile.code_home or "-"
        next_need = profile.next_tasks[0] if profile.next_tasks else "-"
        lines.append(
            f"| {_escape_table(profile.display_name)} | {_escape_table(profile.status)} | {_escape_table(learning_status)} | {_escape_table(checked)} | {_escape_table(source)} | {_escape_table(next_need)} |"
        )
    lines.append("")
    return lines


def _discovery_results_section() -> list[str]:
    items = _discovery_cache()
    lines = [
        "## Municipal Code Discovery",
        "",
        "This section tracks the journal requirement to compile and monitor municipal code sources, not merely test parcels.",
        "",
    ]
    if not items:
        lines.extend(["- No municipal discovery cache has been recorded yet.", ""])
        return lines
    lines.extend(
        [
            "| Municipality | Bot | Registered | Discovery Status | Best Source |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for item in items:
        lines.append(
            f"| {_escape_table(str(item.get('municipality') or '-'))} | {_escape_table(str(item.get('bot') or '-'))} | {'Yes' if item.get('registered') else 'No'} | {_escape_table(str(item.get('recommended_status') or '-'))} | {_escape_table(str(item.get('best_source') or '-'))} |"
        )
    lines.append("")
    return lines


def _bot_cache(key: str) -> dict[str, object]:
    path = BOT_CACHE_ROOT / _safe_name(key) / "latest.json"
    if not path.exists():
        return {}
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {"learn_status": "Cache read error"}


def _discovery_cache() -> list[dict[str, object]]:
    if not DISCOVERY_CACHE_PATH.exists():
        return []
    try:
        import json

        data = json.loads(DISCOVERY_CACHE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return [{"municipality": "Discovery cache", "bot": "-", "registered": False, "recommended_status": "Cache read error", "best_source": ""}]


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "UNKNOWN"


def _parcel_section(parcel: CalibrationParcel, result: FeasibilityResult | None, error: str | None) -> list[str]:
    lines = [f"### {parcel.parcel_number}", "", f"- **Purpose**: {parcel.purpose}", f"- **Expected signal**: {parcel.expected_signal}"]
    if error or result is None:
        lines.extend(["- **Status**: Failed", "", "```text", (error or "Unknown error").strip(), "```", ""])
        return lines

    zoning = ", ".join(district.code for district in result.zoning_districts) or "not found"
    best = result.recommendations[0] if result.recommendations else None
    lines.extend(
        [
            f"- **Status**: {result.status}",
            f"- **Resolved parcel**: {result.parcel.parcel_number}",
            f"- **Municipality**: {result.municipality or 'Unincorporated'}",
            f"- **Zoning**: {zoning}",
            f"- **Owner**: {result.parcel.owner or '-'}",
            f"- **Area**: {result.parcel_area_sf / 43560:,.2f} ac",
            f"- **Best current option**: {_recommendation_line(best)}",
            f"- **Interpretation check**: {_interpretation_check(parcel.parcel_number, result)}",
            "",
            "| Rank | Option | Status | Yield | Value Screen | Key Note |",
            "| --- | --- | --- | ---: | --- | --- |",
        ]
    )

    for index, recommendation in enumerate(result.recommendations[:5], 1):
        lines.append(
            f"| {index} | {_escape_table(recommendation.development_option)} | {_escape_table(recommendation.status)} | {_yield_text(recommendation)} | {_value_text(recommendation)} | {_escape_table(_shorten(recommendation.note, 140))} |"
        )

    present_resources = [resource for resource in result.protected_resources if resource.measured_acres >= 0.005]
    if present_resources:
        lines.extend(["", "**Protected Resources Present**", ""])
        for resource in present_resources:
            lines.append(f"- {resource.name}: {resource.measured_acres:,.2f} measured ac, {resource.protected_acres:,.2f} protected ac")
    else:
        lines.extend(["", "**Protected Resources Present**", "", "- None measured by encoded layers."])

    lines.append("")
    return lines


def _recommendation_line(recommendation: YieldRecommendation | None) -> str:
    if recommendation is None:
        return "No recommendation"
    return f"{recommendation.development_option} ({recommendation.status}) - {_yield_text(recommendation)}"


def _yield_text(recommendation: YieldRecommendation) -> str:
    if recommendation.conservative_yield is None:
        return "-"
    option = recommendation.development_option.lower()
    note = recommendation.note
    note_lower = note.lower()
    if "mixed" in option:
        support_match = re.search(r"residential unit support ([\d,]+)", note, re.IGNORECASE)
        if recommendation.gross_area_yield and support_match:
            return f"{support_match.group(1)} units + {recommendation.gross_area_yield:,} sf GFA"
        program_match = re.search(r"from ([\d,]+) sf commercial GFA and ([\d,]+) apartments", note, re.IGNORECASE)
        if program_match:
            return f"{program_match.group(2)} units + {program_match.group(1)} sf GFA"
        commercial_match = re.search(r"commercial GFA ([\d,]+) sf", note, re.IGNORECASE)
        apartment_match = re.search(r"(?:apartment units|residential unit support) ([\d,]+)", note, re.IGNORECASE)
        if commercial_match and apartment_match:
            return f"{apartment_match.group(1)} units + {commercial_match.group(1)} sf GFA"
    if "single-family" in option or "lot" in option:
        return f"{recommendation.conservative_yield:,} lots"
    if "apartment" in option or "unit" in note_lower:
        return f"{recommendation.conservative_yield:,} units"
    return f"{recommendation.conservative_yield:,} sf"


def _value_text(recommendation: YieldRecommendation) -> str:
    if recommendation.market_value_low is None or recommendation.market_value_high is None:
        return "-"
    return f"${recommendation.market_value_low:,.0f}-${recommendation.market_value_high:,.0f}"


def _interpretation_check(parcel_number: str, result: FeasibilityResult) -> str:
    if parcel_number == "0804930379":
        mixed = _find_option(result, "mixed")
        if mixed and mixed.conservative_yield and "173" in mixed.note and "25,416" in mixed.note:
            return "Pass - mixed-use calibration signal remains present."
        if mixed and mixed.conservative_yield:
            return "Review - mixed-use exists, but the known calibration wording/range changed."
        return "Fail - mixed-use calibration option is missing or not yielding."

    if parcel_number in {"0902800058", "1105400001"}:
        top = result.recommendations[0] if result.recommendations else None
        if top and "public" in top.market_basis.lower():
            return "Review - public-owner context is visible on the top-ranked option."
        civic = next((item for item in result.recommendations if "public" in item.market_basis.lower()), None)
        if civic:
            return "Pass - public-owner context is present and not necessarily top-ranked."
        return "Review - public-owner context was not detected in the visible recommendations."

    if parcel_number.lower() == "1021 gilpin avenue":
        codes = {district.code.upper() for district in result.zoning_districts}
        if result.parcel.parcel_number == "2602130233" and result.municipality.upper() == "WILMINGTON":
            if {"R-3", "R-5-C"}.issubset(codes):
                return "Pass - Wilmington review resolves the address and marks the non-bounded zoning distinction for materiality review."
            return "Review - Wilmington address resolves correctly, but municipal zoning overlap was not available in this run."
        return "Fail - Wilmington address lookup did not resolve to expected parcel 2602130233."

    if parcel_number.lower() == "2000 pennsylvania avenue":
        options = {item.development_option.lower(): item for item in result.recommendations}
        top = result.recommendations[0] if result.recommendations else None
        if result.parcel.parcel_number != "2602010008" or result.municipality.upper() != "WILMINGTON":
            return "Fail - Wilmington C-2 calibration address did not resolve to parcel 2602010008 in Wilmington."
        if "apartments" in options and "mixed use" in options and top and top.development_option.lower() == "apartments":
            return "Pass - C-2 imports R-5-C residential permissions and ranks apartments/mixed-use ahead of generic commercial GFA."
        if "apartments" in options or "mixed use" in options:
            return "Review - C-2 inherited residential path exists, but ranking or mixed-use output changed."
        return "Fail - C-2 inherited R-5-C apartment/mixed-use screen is missing."

    municipality = (result.municipality or "").lower()
    if municipality and "unincorporated" not in municipality:
        if "municipal" in result.summary.lower() or result.status.lower() == "review required":
            return "Pass - incorporated municipality is not treated as county-code yield."
        return "Review - incorporated parcel may need a municipality profile."

    return "Pass - no calibration-specific exception triggered."


def _find_option(result: FeasibilityResult, needle: str) -> YieldRecommendation | None:
    needle = needle.lower()
    return next((item for item in result.recommendations if needle in item.development_option.lower()), None)


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _shorten(value: str, limit: int) -> str:
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


if __name__ == "__main__":
    raise SystemExit(main())
