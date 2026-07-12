from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parcel_packet.environmental_runner import EnvironmentalMapsRunner


OUT = Path("_inspect_environmental_real_expand")


def progress(message: str) -> None:
    print(message, flush=True)


def dump(page, name: str) -> None:
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)
    data = page.locator("[aria-label], [title], button, calcite-action, calcite-list-item").evaluate_all(
        """els => els.map((e, i) => {
            const r = e.getBoundingClientRect();
            return {
                i,
                tag: e.tagName,
                title: e.getAttribute("title"),
                aria: e.getAttribute("aria-label"),
                expanded: e.getAttribute("aria-expanded"),
                role: e.getAttribute("role"),
                cls: typeof e.className === "string" ? e.className.slice(0, 120) : "",
                text: (e.innerText || e.textContent || "").trim().replace(/\\s+/g, " ").slice(0, 180),
                visible: r.width > 0 && r.height > 0,
                rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}
            };
        }).filter(x => x.visible && /Environmental|FEMA|Flood|Wetland|NHD|Forest|Critical|Coastal|Swamp|Marsh|WRPA|Watershed/i.test([x.title, x.aria, x.text].join(" ")))"""
    )
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"saved {name}", flush=True)
    for item in data:
        print(item, flush=True)


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

            clicked = map_page.evaluate(
                """() => {
                    const visible = (element) => {
                        const box = element.getBoundingClientRect();
                        return box.width > 0 && box.height > 0;
                    };
                    const rows = [...document.querySelectorAll('[aria-label="Environmental"]')].filter(visible);
                    for (const row of rows) {
                        const expand = row.querySelector('.expanded-container[title="Expand"], .expanded-container');
                        if (!expand || !visible(expand)) continue;
                        expand.click();
                        const rowBox = row.getBoundingClientRect();
                        const expandBox = expand.getBoundingClientRect();
                        return {
                            rowTag: row.tagName,
                            rowAria: row.getAttribute("aria-label"),
                            rowExpanded: row.getAttribute("aria-expanded"),
                            rowBox: {x: rowBox.x, y: rowBox.y, w: rowBox.width, h: rowBox.height},
                            expandBox: {x: expandBox.x, y: expandBox.y, w: expandBox.width, h: expandBox.height},
                            expandHtml: expand.outerHTML.slice(0, 500)
                        };
                    }
                    return null;
                }"""
            )
            print("clicked", json.dumps(clicked, indent=2), flush=True)
            map_page.wait_for_timeout(1000)
            dump(map_page, "02-after-real-expand")
        finally:
            context.close()
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
