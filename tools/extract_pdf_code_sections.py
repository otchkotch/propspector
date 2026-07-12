from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

import pdfplumber


ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "cache" / "municipal-sections"


@dataclass(frozen=True)
class PdfSection:
    query: str
    title: str
    url: str
    extracted_at: str
    text: str


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract municipal code sections from a PDF source.")
    parser.add_argument("municipality")
    parser.add_argument("pdf")
    parser.add_argument("--source-url", default="")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    text = _read_pdf(pdf_path)
    sections = _split_sections(text, args.source_url or str(pdf_path))
    if not sections:
        sections = [PdfSection("full pdf", pdf_path.stem, args.source_url or str(pdf_path), datetime.now().isoformat(timespec="seconds"), text)]

    out_dir = OUT_ROOT / args.municipality.lower().replace(" ", "_")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "latest.json"
    new_items = [asdict(section) for section in sections if len(section.text) >= 80]
    merged = new_items if args.replace else _merge_existing(out_path, new_items)
    out_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")
    print(f"sections {len(merged)}")
    for item in merged[:80]:
        print(f"- {item.get('title')} ({len(str(item.get('text') or ''))} chars)")
    return 0 if merged else 1


def _read_pdf(path: Path) -> str:
    pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        print(f"pages {len(pdf.pages)}")
        for index, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
            pages.append(f"\n\n[PDF page {index}]\n{page_text}")
    return "\n".join(pages)


def _split_sections(text: str, source_url: str) -> list[PdfSection]:
    normalized = "\n".join(line.rstrip() for line in text.splitlines())
    heading_pattern = re.compile(
        r"(?m)^(?P<title>(?:ARTICLE|SECTION|Sec\.|§)\s+[A-Z0-9IVXLCDM_.:-]+[^\n]{0,140})$",
        re.IGNORECASE,
    )
    matches = list(heading_pattern.finditer(normalized))
    sections: list[PdfSection] = []
    now = datetime.now().isoformat(timespec="seconds")
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        title = " ".join(match.group("title").split())
        body = normalized[start:end].strip()
        if len(body) < 80:
            continue
        sections.append(PdfSection(query=title, title=title, url=source_url, extracted_at=now, text=body))
    return sections


def _merge_existing(path: Path, new_items: list[dict[str, str]]) -> list[dict[str, str]]:
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        existing = []
    merged: dict[str, dict[str, str]] = {}
    for item in existing if isinstance(existing, list) else []:
        if isinstance(item, dict):
            merged[str(item.get("query") or item.get("title") or len(merged))] = item
    for item in new_items:
        merged[str(item.get("query") or item.get("title") or len(merged))] = item
    return list(merged.values())


if __name__ == "__main__":
    raise SystemExit(main())
