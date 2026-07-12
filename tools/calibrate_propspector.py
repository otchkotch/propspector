from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from parcel_packet.zoning_feasibility_runner import ZoningFeasibilityRunner


DEV_ACTIVITY_URL = "https://gis.nccde.org/agsserver/rest/services/BaseMaps/LandUse/MapServer/3/query"
PARCEL_SEARCH_URL = "https://www3.newcastlede.gov/parcel/search/"


@dataclass(frozen=True)
class Project:
    app_no: str
    parcel: str
    name: str
    work_type: str
    status: str
    description: str
    recorded: int | None
    url: str


def fetch_json(url: str, params: dict[str, str]) -> dict:
    data = urllib.parse.urlencode(params).encode("utf-8")
    with urllib.request.urlopen(url, data=data, timeout=60) as response:
        return json.load(response)


def development_projects(where: str = "1=1", limit: int = 200) -> list[Project]:
    data = fetch_json(
        DEV_ACTIVITY_URL,
        {
            "f": "json",
            "where": where,
            "outFields": "APP_NO,parcelid,projname,worktype,status,descript,recorded,URL",
            "returnGeometry": "false",
            "orderByFields": "OBJECTID DESC",
            "resultRecordCount": str(limit),
        },
    )
    projects = []
    for feature in data.get("features") or []:
        attrs = feature.get("attributes") or {}
        projects.append(
            Project(
                app_no=str(attrs.get("APP_NO") or ""),
                parcel="".join(ch for ch in str(attrs.get("parcelid") or "") if ch.isalnum()),
                name=str(attrs.get("projname") or ""),
                work_type=str(attrs.get("worktype") or ""),
                status=str(attrs.get("status") or ""),
                description=str(attrs.get("descript") or ""),
                recorded=attrs.get("recorded"),
                url=str(attrs.get("URL") or ""),
            )
        )
    return projects


def recent_recorded_projects() -> list[Project]:
    return development_projects("recorded IS NOT NULL", 200)


def expected_yield(project: Project) -> tuple[str, int] | None:
    text = " ".join((project.name, project.work_type, project.description)).lower()
    patterns = (
        (r"(\d[\d,]*)\s+(?:single family|single-family|residential)?\s*lots?", "lots"),
        (r"(\d[\d,]*)\s+(?:dwelling\s+)?units?", "units"),
        (r"(\d[\d,]*)\s+apartments?", "units"),
        (r"(\d[\d,]*)\s+townhomes?", "units"),
        (r"(\d[\d,]*)\s+townhouses?", "units"),
        (r"(\d[\d,]*)\s+sf", "sf GFA"),
        (r"(\d[\d,]*)\s+sq\.?\s*ft", "sf GFA"),
    )
    for pattern, unit in patterns:
        match = re.search(pattern, text)
        if match:
            return unit, int(match.group(1).replace(",", ""))
    return None


def fetch_html(url: str, data: dict[str, str] | None = None) -> str:
    encoded = urllib.parse.urlencode(data).encode() if data else None
    with urllib.request.urlopen(urllib.request.Request(url, data=encoded), timeout=60) as response:
        return response.read().decode("utf-8", "ignore")


def hidden_fields(html: str) -> dict[str, str]:
    return {
        name: value
        for name, value in re.findall(r'<input type="hidden" name="([^"]+)" id="[^"]+" value="([^"]*)"', html)
    }


def parcel_search_count(parcel: str) -> int | None:
    try:
        html = fetch_html(PARCEL_SEARCH_URL)
        data = hidden_fields(html)
        data.update(
            {
                "ctl00$ctl00$ContentPlaceHolder1$ContentPlaceHolder1$_TextBoxParcelNumber": parcel,
                "ctl00$ctl00$ContentPlaceHolder1$ContentPlaceHolder1$_ButtonSearch": "Search",
            }
        )
        result = fetch_html(PARCEL_SEARCH_URL, data)
    except Exception:
        return None
    match = re.search(r"There are\s+([\d,]+)\s+parcels matching", result, re.I)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def recommendation_number(text: str) -> int | None:
    match = re.search(r"(\d[\d,]*)", text)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def main() -> None:
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "candidates":
        found = 0
        for project in development_projects("1=1", 120):
            if not project.parcel:
                continue
            count = parcel_search_count(project.parcel)
            if count and count >= 5:
                print(project.app_no, project.parcel, count, project.name, project.work_type, project.status, project.description)
                found += 1
            if found >= 20:
                break
        return

    checked = 0
    for project in recent_recorded_projects():
        if not project.parcel:
            continue
        expected = expected_yield(project)
        parcel_count = parcel_search_count(project.parcel)
        try:
            result = ZoningFeasibilityRunner(project.parcel).analyze()
        except Exception as exc:
            print(f"SKIP {project.app_no} {project.name}: {exc}")
            continue
        if result.municipality != "Unincorporated New Castle County":
            continue
        acres = result.parcel_area_sf / 43560.0
        if acres < 5:
            continue
        best = result.recommendations[0] if result.recommendations else None
        estimated = best.conservative_yield if best else None
        print("\nPROJECT", project.app_no, project.name)
        print("parcel", project.parcel, "acres", f"{acres:.2f}", "zoning", ",".join(d.code for d in result.zoning_districts))
        print("work", project.work_type, "status", project.status)
        print("description", project.description)
        print("description expected", f"{expected[1]} {expected[0]}" if expected else "-")
        print("parcel-site matching row count", parcel_count)
        if best:
            print("best", best.development_option, best.status, estimated, best.market_basis)
            print("note", best.note[:300])
        else:
            print("best none")
        checked += 1
        if checked >= 8:
            break


if __name__ == "__main__":
    main()
