from __future__ import annotations

import argparse
import json
import mimetypes
import re
import sys
import threading
import uuid
import webbrowser
from dataclasses import asdict, is_dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .zoning_feasibility_runner import (
    APARTMENT_UNIT_SIZE_MIX,
    COUNTY_CODE_HOME,
    ENVIRONMENTAL_MAPSERVER_URL,
    MAP_SPATIAL_REFERENCE,
    MIXED_USE_COMMERCIAL_GFA_SHARE,
    MIXED_USE_PROGRAM_GFA_UTILIZATION,
    MIXED_USE_RESIDENTIAL_GROSS_EFFICIENCY,
    WRPA_MAPSERVER_URL,
    FeasibilityResult,
    YieldRecommendation,
    ZoningFeasibilityRunner,
)


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
WEB_ROOT = ROOT / "web" / "zoning_feasibility"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


class ZoningWebHandler(BaseHTTPRequestHandler):
    server_version = "ZoningFeasibilityWeb/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/report":
            self._handle_report(parse_qs(parsed.query))
            return
        if parsed.path == "/api/config":
            self._send_json(
                {
                    "countyCodeHome": COUNTY_CODE_HOME,
                    "environmentalMapServerUrl": ENVIRONMENTAL_MAPSERVER_URL,
                    "wrpaMapServerUrl": WRPA_MAPSERVER_URL,
                    "mapSpatialReference": int(MAP_SPATIAL_REFERENCE),
                }
            )
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/analyze":
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
            return
        payload = self._read_json()
        parcel = str(payload.get("parcel") or "").strip()
        intended_use = str(payload.get("intendedUse") or "").strip()
        if not parcel:
            self._send_json({"error": "Enter at least one parcel number."}, HTTPStatus.BAD_REQUEST)
            return

        progress: list[str] = []
        try:
            runner = ZoningFeasibilityRunner(parcel, intended_use=intended_use, progress=progress.append)
            result = runner.analyze()
            token = self._store_report(runner, result)
        except Exception as exc:
            self._send_json({"error": str(exc), "progress": progress}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._send_json(
            {
                "progress": progress,
                "reportToken": token,
                "result": result_to_payload(result),
            }
        )

    def log_message(self, format: str, *args: object) -> None:
        return

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _serve_static(self, path: str) -> None:
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        target = (WEB_ROOT / relative).resolve()
        try:
            target.relative_to(WEB_ROOT.resolve())
        except ValueError:
            self.send_error(HTTPStatus.FORBIDDEN, "Invalid path")
            return
        if not target.exists() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _store_report(self, runner: ZoningFeasibilityRunner, result: FeasibilityResult) -> str:
        token = uuid.uuid4().hex
        report_text = runner._report_text(result)
        self.server.reports[token] = report_text  # type: ignore[attr-defined]
        return token

    def _handle_report(self, query: dict[str, list[str]]) -> None:
        token = (query.get("token") or [""])[0]
        report = self.server.reports.get(token)  # type: ignore[attr-defined]
        if not report:
            self.send_error(HTTPStatus.NOT_FOUND, "Report not found")
            return
        data = report.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="Zoning Feasibility Report.txt"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ZoningHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_class: type[BaseHTTPRequestHandler]) -> None:
        super().__init__(server_address, handler_class)
        self.reports: dict[str, str] = {}


def result_to_payload(result: FeasibilityResult) -> dict[str, object]:
    best = result.recommendations[0] if result.recommendations else None
    return {
        "status": result.status,
        "confidence": result.confidence,
        "summary": result.summary,
        "headline": headline(result, best),
        "details": result.details,
        "standards": result.standards,
        "sources": result.sources,
        "parcel": dataclass_to_dict(result.parcel),
        "municipality": result.municipality,
        "zoningDistricts": [dataclass_to_dict(district) for district in result.zoning_districts],
        "parcelAreaSf": result.parcel_area_sf,
        "shapeEfficiency": result.shape_efficiency,
        "recommendations": [recommendation_to_payload(result, item) for item in result.recommendations],
        "protectedResources": [dataclass_to_dict(item) for item in result.protected_resources],
        "capacityMatrix": dataclass_to_dict(result.capacity_matrix) if result.capacity_matrix else None,
        "geometry": result.parcel.geometry,
    }


def recommendation_to_payload(result: FeasibilityResult, item: YieldRecommendation) -> dict[str, object]:
    payload = dataclass_to_dict(item)
    payload["displayName"] = display_name(item.development_option)
    payload["yieldText"] = yield_text(result, item)
    payload["marketText"] = market_text(item)
    payload["isAvailable"] = item.conservative_yield is not None and item.conservative_yield > 0 and item.status != "Not By Right"
    return payload


def dataclass_to_dict(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if is_dataclass(value):
        return asdict(value)
    return value  # type: ignore[return-value]


def headline(result: FeasibilityResult, best: YieldRecommendation | None) -> str:
    if not best or best.conservative_yield is None:
        return result.summary
    return f"{display_name(best.development_option)}: {yield_text(result, best)}"


def display_name(option: str) -> str:
    clean = option.lower()
    if clean == "mixed use development":
        return "Mixed Use"
    if clean == "commercial apartments":
        return "Apartments"
    if clean == "other / custom use":
        return "Civic / Utility / Solar / Other"
    return option


def yield_text(result: FeasibilityResult, item: YieldRecommendation) -> str:
    if item.conservative_yield is None:
        return "Review required"
    option = item.development_option.lower()
    if "mixed use" in option:
        if item.program_scenario:
            scenario = item.program_scenario
            return f"{scenario.modeled_units or 0:,} units within +/-{(scenario.envelope_gfa or 0):,} sf GFA envelope"
        commercial_gfa, units = mixed_use_split(item)
        return f"{units:,} units within mixed-use GFA program; {commercial_gfa:,} sf commercial component"
    if "solar" in option:
        return f"{item.conservative_yield:,} sf site area"
    if any(label in option for label in ("single-family", "two-family", "townhouse", "semi-detached")):
        return f"{item.conservative_yield:,} lots"
    if any(label in option for label in ("apartment", "manufactured", "mobile", "home")):
        return f"{item.conservative_yield:,} units"
    if result.capacity_matrix and result.capacity_matrix.capacity_type == "nonresidential":
        return f"{item.conservative_yield:,} sf GFA"
    return f"{item.conservative_yield:,}"


def market_text(item: YieldRecommendation) -> str:
    if item.market_basis.startswith("public-owner"):
        return "Public-owner context"
    low = item.market_value_low
    high = item.market_value_high
    if low is None or high is None:
        return "-"
    if low == high:
        return money(low)
    return f"{money(low)}-{money(high)}"


def money(value: int) -> str:
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}k"
    return f"${value:,}"


def mixed_use_split(item: YieldRecommendation) -> tuple[int, int]:
    if item.program_scenario:
        return item.program_scenario.commercial_gfa or 0, item.program_scenario.modeled_units or 0
    allowed_gfa = item.conservative_yield or 0
    program_gfa = int(allowed_gfa * MIXED_USE_PROGRAM_GFA_UTILIZATION)
    commercial_gfa = int(program_gfa * MIXED_USE_COMMERCIAL_GFA_SHARE)
    residential_gfa = max(0, program_gfa - commercial_gfa)
    gfa_units = int((residential_gfa * MIXED_USE_RESIDENTIAL_GROSS_EFFICIENCY) / average_gross_unit_area())
    note_units = [value for value in (mixed_use_note_units(item.note, "residential unit support"), mixed_use_note_units(item.note, "site support")) if value]
    units = min([gfa_units, *note_units]) if note_units else gfa_units
    return commercial_gfa, max(0, units)


def average_gross_unit_area() -> float:
    average_net_area = sum(share * area for _bedroom, share, area in APARTMENT_UNIT_SIZE_MIX)
    return average_net_area / MIXED_USE_RESIDENTIAL_GROSS_EFFICIENCY


def mixed_use_note_units(note: str, label: str) -> int:
    match = re.search(rf"{re.escape(label)} ([\d,]+)", note)
    return int(match.group(1).replace(",", "")) if match else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Zoning Feasibility Checker web workspace.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", default=DEFAULT_PORT, type=int)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    server = ZoningHTTPServer((args.host, args.port), ZoningWebHandler)
    url = f"http://{args.host}:{args.port}/"
    if not args.no_browser:
        threading.Timer(0.75, lambda: webbrowser.open(url)).start()
    print(f"Zoning Feasibility Checker web workspace running at {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
