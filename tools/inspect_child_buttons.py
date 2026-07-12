from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parcel_packet.environmental_runner import EnvironmentalMapsRunner


OUT = Path("_inspect_child_buttons")


def progress(message: str) -> None:
    print(message, flush=True)


def main() -> int:
    OUT.mkdir(exist_ok=True)
    for path in OUT.glob("*"):
        if path.is_file():
            path.unlink()

    with sync_playwright() as playwright:
        runner = EnvironmentalMapsRunner(
            parcel_number="2605000039",
            destination=OUT,
            progress=progress,
            stop_event=threading.Event(),
            pause_seconds=1,
            headless_browser=False,
            offscreen_browser=False,
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
            runner._expand_environmental_sublayers(map_page)
            map_page.wait_for_timeout(1000)
            map_page.screenshot(path=str(OUT / "expanded.png"), full_page=False)
            data = map_page.locator('button[aria-label], calcite-action[title], [role="row"][aria-label], calcite-list-item[title]').evaluate_all(
                """els => els.map((e, i) => {
                    const r = e.getBoundingClientRect();
                    return {
                        i,
                        tag: e.tagName,
                        title: e.getAttribute("title"),
                        aria: e.getAttribute("aria-label"),
                        expanded: e.getAttribute("aria-expanded"),
                        role: e.getAttribute("role"),
                        text: (e.innerText || e.textContent || "").trim().replace(/\\s+/g, " ").slice(0, 180),
                        visible: r.width > 0 && r.height > 0,
                        rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}
                    };
                }).filter(x => x.visible && /Environmental|Buoys|Watersheds|Topography|FEMA|Flood|Wetlands|Swamp|Coastal|Forest|NHD|Critical|WRPA/i.test([x.title, x.aria, x.text].join(" ")))"""
            )
            (OUT / "expanded-controls.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
            print(json.dumps(data, indent=2)[:24000], flush=True)
        finally:
            context.close()
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
