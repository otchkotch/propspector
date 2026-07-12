from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parcel_packet.environmental_runner import EnvironmentalMapsRunner


OUT = Path("_inspect_expand_containers")


def progress(message: str) -> None:
    print(message, flush=True)


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
            map_page.screenshot(path=str(OUT / "before.png"), full_page=False)

            data = map_page.locator('.expanded-container, [title="Expand"], calcite-icon[icon="chevron-right"]').evaluate_all(
                """els => els.map((e, i) => {
                    const r = e.getBoundingClientRect();
                    let node = e;
                    const ancestors = [];
                    for (let level = 0; node && level < 9; level++, node = node.parentElement) {
                        ancestors.push({
                            level,
                            tag: node.tagName,
                            cls: typeof node.className === "string" ? node.className.slice(0, 180) : "",
                            title: node.getAttribute("title"),
                            aria: node.getAttribute("aria-label"),
                            expanded: node.getAttribute("aria-expanded"),
                            role: node.getAttribute("role"),
                            text: (node.innerText || node.textContent || "").trim().replace(/\\s+/g, " ").slice(0, 180)
                        });
                    }
                    return {
                        i,
                        tag: e.tagName,
                        cls: typeof e.className === "string" ? e.className.slice(0, 180) : "",
                        title: e.getAttribute("title"),
                        aria: e.getAttribute("aria-label"),
                        icon: e.getAttribute("icon"),
                        visible: r.width > 0 && r.height > 0,
                        rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)},
                        ancestors
                    };
                })"""
            )
            (OUT / "containers.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
            print(json.dumps(data, indent=2)[:30000], flush=True)
        finally:
            context.close()
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
