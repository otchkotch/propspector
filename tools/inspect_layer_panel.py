from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parcel_packet.aerial_runner import AerialMapRunner


PARCEL = "0612700002"
OUT = Path("layer-panel-inspection")


def progress(message: str) -> None:
    print(message, flush=True)


def main() -> int:
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        runner = AerialMapRunner(
            parcel_number=PARCEL,
            destination=OUT,
            progress=progress,
            stop_event=__import__("threading").Event(),
            pause_seconds=2,
        )
        browser = runner._launch_browser(playwright)
        context = browser.new_context(viewport={"width": 1600, "height": 900}, device_scale_factor=1)
        page = context.new_page()
        page.set_default_timeout(30_000)
        try:
            runner._open_search(page)
            runner._search(page)
            runner._open_first_result(page)
            map_page = runner._open_map(page)
            runner._close_popups(map_page)
            map_page.screenshot(path=str(OUT / "map-before-panel.png"), full_page=False)

            toolbar = map_page.locator("div[title], button[title], a[title], div[role='button'], button, a").evaluate_all(
                """els => els.map((e, i) => {
                    const r = e.getBoundingClientRect();
                    return {
                        i,
                        tag: e.tagName,
                        title: e.getAttribute("title"),
                        aria: e.getAttribute("aria-label"),
                        role: e.getAttribute("role"),
                        text: (e.innerText || e.value || "").trim().slice(0, 120),
                        cls: typeof e.className === "string" ? e.className.slice(0, 160) : "",
                        rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}
                    };
                }).filter(x => x.title || x.aria || x.role || x.text || x.cls.includes("jimu-icon"))"""
            )
            (OUT / "toolbar.json").write_text(json.dumps(toolbar, indent=2), encoding="utf-8")

            runner._open_layer_panel(map_page)
            map_page.wait_for_timeout(2000)
            map_page.screenshot(path=str(OUT / "layer-panel-open.png"), full_page=False)

            data = map_page.locator(".checkbox.jimu-float-leading.jimu-icon.jimu-icon-checkbox, .jimu-icon-checkbox").evaluate_all(
                """els => els.map((e, i) => {
                    const r = e.getBoundingClientRect();
                    let node = e;
                    const ancestors = [];
                    for (let level = 0; node && level < 8; level++, node = node.parentElement) {
                        ancestors.push({
                            level,
                            tag: node.tagName,
                            cls: typeof node.className === "string" ? node.className.slice(0, 180) : "",
                            text: (node.innerText || "").trim().replace(/\\s+/g, " ").slice(0, 300)
                        });
                    }
                    return {
                        i,
                        visible: !!(r.width && r.height),
                        cls: typeof e.className === "string" ? e.className : "",
                        rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)},
                        ancestors
                    };
                })"""
            )
            (OUT / "checkboxes.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
            print(json.dumps(data, indent=2)[:12000])
        finally:
            context.close()
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
