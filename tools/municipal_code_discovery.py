from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DISCOVERY_ROOT = PROJECT_ROOT / "wiki" / "municipal-discovery"
CACHE_ROOT = PROJECT_ROOT / "cache" / "municipal-discovery"
MUNICIPALITY_QUERY_URL = "https://gis.nccde.org/agsserver/rest/services/BaseMaps/Base_Layers/MapServer/2/query"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from parcel_packet.municipal_bots import has_named_municipal_bot, municipal_bot_for


USER_AGENT = "PropSpector municipal code discovery; low-frequency source check"
OFFICIAL_HOME_CANDIDATES: dict[str, tuple[str, ...]] = {
    "ARDEN": ("https://arden.delaware.gov/",),
    "ARDENCROFT": ("https://ardencroft.delaware.gov/",),
    "ARDENTOWN": ("https://ardentown.delaware.gov/",),
    "BELLEFONTE": ("https://bellefonte.delaware.gov/",),
    "CLAYTON": ("https://clayton.delaware.gov/",),
    "DELAWARE CITY": ("https://delawarecity.delaware.gov/",),
    "ELSMERE": ("https://townofelsmere.com/", "https://elsmere.delaware.gov/"),
    "MIDDLETOWN": ("https://www.middletown.delaware.gov/",),
    "NEW CASTLE": ("https://newcastlecity.delaware.gov/",),
    "NEWARK": ("https://newarkde.gov/",),
    "NEWPORT": ("https://newport.delaware.gov/",),
    "ODESSA": ("https://odessa.delaware.gov/",),
    "SMYRNA": ("https://smyrna.delaware.gov/",),
    "TOWNSEND": ("https://townsend.delaware.gov/",),
    "WILMINGTON": ("https://www.wilmingtonde.gov/",),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover NCC municipal code-source candidates for PropSpector bots.")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds to wait between source checks.")
    parser.add_argument("--no-write", action="store_true", help="Print report only; do not write cache/wiki files.")
    args = parser.parse_args()

    municipalities = _ncc_municipalities()
    results = []
    for index, name in enumerate(municipalities):
        if index:
            time.sleep(max(0.0, args.delay))
        results.append(_discover_municipality(name, args.delay))

    report = _render_report(results)
    if args.no_write:
        print(report)
        return 0

    DISCOVERY_ROOT.mkdir(parents=True, exist_ok=True)
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    today = datetime.now().date().isoformat()
    (DISCOVERY_ROOT / "latest.md").write_text(report, encoding="utf-8")
    (DISCOVERY_ROOT / f"{today}.md").write_text(report, encoding="utf-8")
    (CACHE_ROOT / "latest.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Wrote {DISCOVERY_ROOT / 'latest.md'}")
    return 0


def _ncc_municipalities() -> list[str]:
    data = _post_json(
        MUNICIPALITY_QUERY_URL,
        {
            "f": "json",
            "where": "1=1",
            "outFields": "NAME",
            "returnGeometry": "false",
            "returnDistinctValues": "true",
            "orderByFields": "NAME",
        },
    )
    names = [
        str((feature.get("attributes") or {}).get("NAME") or "").strip().upper()
        for feature in data.get("features", [])
    ]
    return sorted({name for name in names if name})


def _discover_municipality(name: str, delay: float) -> dict[str, object]:
    bot = municipal_bot_for(name)
    candidates = _candidate_urls(name, bot.code_home)
    checked = []
    for index, url in enumerate(candidates[:8]):
        if index:
            time.sleep(max(0.0, min(delay, 2.0)))
        checked.append(_check_url(url))
    reachable = [item for item in checked if item["reachable"]]
    code_like = [item for item in reachable if _looks_like_code_source(item)]
    return {
        "municipality": name,
        "bot": bot.display_name,
        "bot_status": bot.status,
        "registered": has_named_municipal_bot(name),
        "candidate_count": len(candidates),
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "recommended_status": _recommended_status(bot.status, code_like, reachable),
        "checked_sources": checked,
        "best_source": code_like[0]["url"] if code_like else (reachable[0]["url"] if reachable else ""),
        "next_need": bot.next_tasks[0] if bot.next_tasks else "Create municipality bot profile.",
    }


def _candidate_urls(name: str, registered_url: str) -> list[str]:
    slug = _slug(name)
    compact = slug.replace("_", "")
    spaced = name.lower().replace(" ", "-")
    candidates = [
        registered_url,
        f"https://library.municode.com/de/{slug}/codes/code_of_ordinances",
        f"https://library.municode.com/de/{compact}/codes/code_of_ordinances",
        f"https://ecode360.com/{name.replace(' ', '')}DE",
        f"https://ecode360.com/{compact.upper()}",
        *OFFICIAL_HOME_CANDIDATES.get(name, ()),
        f"https://{spaced}.delaware.gov/",
        f"https://{compact}.delaware.gov/",
    ]
    clean = []
    seen = set()
    for url in candidates:
        if not url or url in seen:
            continue
        seen.add(url)
        clean.append(url)
    return clean


def _check_url(url: str) -> dict[str, object]:
    result: dict[str, object] = {
        "url": url,
        "reachable": False,
        "status": None,
        "title": "",
        "signals": (),
        "note": "",
    }
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(300_000)
            result["status"] = getattr(response, "status", 200)
            charset = response.headers.get_content_charset() or "utf-8"
        text = raw.decode(charset, errors="replace")
        result["reachable"] = True
        result["title"] = _title(text)
        result["signals"] = tuple(_source_signals(url, text))
    except urllib.error.HTTPError as exc:
        result["status"] = exc.code
        result["note"] = "blocked or missing" if exc.code in {401, 403, 404, 429} else f"HTTP error {exc.code}"
    except Exception as exc:
        result["note"] = exc.__class__.__name__
    return result


def _source_signals(url: str, text: str) -> list[str]:
    visible = _visible_text(text).lower()
    signals = []
    if "municode" in url or "municode" in visible:
        signals.append("municode")
    if "ecode360" in url or "ecode360" in visible:
        signals.append("ecode360")
    for term in ("zoning", "ordinance", "code", "subdivision", "parking", "land use"):
        if term in visible:
            signals.append(term)
    return signals[:8]


def _looks_like_code_source(item: dict[str, object]) -> bool:
    signals = set(item.get("signals") or ())
    return bool({"municode", "ecode360", "zoning", "ordinance", "code"} & signals)


def _recommended_status(bot_status: str, code_like: list[dict[str, object]], reachable: list[dict[str, object]]) -> str:
    if code_like and "Seed Bot" in bot_status:
        return "Source candidate found; bot should learn section map next"
    if code_like:
        return "Source candidate reachable"
    if reachable:
        return "Official homepage reachable; code source still needs discovery"
    return "Discovery blocked or source missing"


def _post_json(url: str, params: dict[str, str]) -> dict:
    request = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode("utf-8"), method="POST")
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def _visible_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return " ".join(text.split())


def _title(html: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    return " ".join(re.sub(r"<[^>]+>", " ", match.group(1)).split()) if match else ""


def _render_report(results: list[dict[str, object]]) -> str:
    lines = [
        f"# Municipal Code Discovery - {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Journal Priority",
        "",
        "This report implements the journal instruction that PropSpector should seek municipal codes through Municode, eCode360, official PDFs, and official web sources, compile jurisdictions, and monitor them for changes.",
        "",
        "## NCC Municipality Coverage",
        "",
        "| Municipality | Bot | Registered | Discovery Status | Best Source | Next Need |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in results:
        lines.append(
            f"| {_escape(str(item['municipality']))} | {_escape(str(item['bot']))} | {'Yes' if item['registered'] else 'No'} | {_escape(str(item['recommended_status']))} | {_escape(str(item['best_source']) or '-')} | {_escape(str(item['next_need']))} |"
        )
    lines.extend(["", "## Checked Sources", ""])
    for item in results:
        lines.extend([f"### {item['municipality']}", ""])
        for source in item["checked_sources"]:
            signals = ", ".join(source.get("signals") or ()) or "-"
            status = source.get("status") or "-"
            note = source.get("note") or "-"
            lines.append(f"- `{source['url']}`: status {status}; reachable {source['reachable']}; signals {signals}; note {note}")
        lines.append("")
    return "\n".join(lines)


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


if __name__ == "__main__":
    raise SystemExit(main())
