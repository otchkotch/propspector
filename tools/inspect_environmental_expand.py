from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parcel_packet.environmental_runner import EnvironmentalMapsRunner


OUT = Path("_inspect_environmental_expand")


def progress(message: str) -> None:
    print(message, flush=True)


def dump(page, name: str) -> None:
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)
    data = page.locator("button[aria-label], calcite-action[title], calcite-list-item[title], [title]").evaluate_all(
        """els => els.map((e, i) => {
            const r = e.getBoundingClientRect();
            return {
                i,
                tag: e.tagName,
                title: e.getAttribute("title"),
                aria: e.getAttribute("aria-label"),
                text: (e.innerText || e.textContent || "").trim().replace(/\\s+/g, " ").slice(0, 120),
                visible: r.width > 0 && r.height > 0,
                rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}
            };
        }).filter(x => x.visible && /Environmental|FEMA|Flood|Wetland|NHD|Forest|Critical|Coastal|Swamp|Marsh|WRPA/i.test([x.title, x.aria, x.text].join(" ")))"""
    )
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"saved {name}", flush=True)
    for item in data:
        print(item, flush=True)
    try:
        row_data = page.locator("calcite-list-item[title='Environmental']").first.evaluate(
            """row => {
            return [row, ...row.querySelectorAll("*")].map((e, i) => {
                const r = e.getBoundingClientRect();
                return {
                    i,
                    tag: e.tagName,
                    title: e.getAttribute("title"),
                    aria: e.getAttribute("aria-label"),
                    role: e.getAttribute("role"),
                    text: (e.innerText || e.textContent || "").trim().replace(/\\s+/g, " ").slice(0, 120),
                    visible: r.width > 0 && r.height > 0,
                    rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}
                };
            }).filter((item) => item.visible);
        }"""
        )
    except Exception as exc:
        row_data = {"error": str(exc)}
    (OUT / f"{name}-environmental-row.json").write_text(json.dumps(row_data, indent=2), encoding="utf-8")


def main() -> int:
    OUT.mkdir(exist_ok=True)
    for path in OUT.glob("*"):
        if path.is_file():
            path.unlink()

    with sync_playwright() as playwright:
        runner = EnvironmentalMapsRunner(
            parcel_number="0612700002",
            destination=OUT,
            progress=progress,
            stop_event=threading.Event(),
            pause_seconds=1,
        )
        browser = runner._launch_browser(playwright)
        context = browser.new_context(viewport={"width": 1600, "height": 900}, device_scale_factor=2)
        page = context.new_page()
        page.set_default_timeout(30_000)
        try:
            runner._open_search(page)
            runner._search(page)
            runner._open_first_result(page)
            map_page = runner._open_map(page)
            runner._prepare_aerial_base_for_environmental(map_page)
            runner._ensure_layer_manager_available(map_page)
            runner._ensure_environmental_layers_visible(map_page)
            map_page.wait_for_timeout(800)
            dump(map_page, "01-env-on")

            row = map_page.locator("calcite-list-item[title='Environmental']").first
            box = row.bounding_box()
            print(f"env row box {box}", flush=True)
            if box is None:
                raise RuntimeError("Environmental row has no bounding box")
            map_page.mouse.click(box["x"] + box["width"] - 93, box["y"] + box["height"] / 2)
            map_page.wait_for_timeout(1000)
            dump(map_page, "02-after-expand-click")
        finally:
            context.close()
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
