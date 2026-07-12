from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parcel_packet.environmental_runner import EnvironmentalMapsRunner


PARCEL = "0612700002"
OUT = Path("_diagnose_environmental")


def progress(message: str) -> None:
    print(message, flush=True)


def shot(page: Page, name: str) -> None:
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)
    dump_buttons(page, name)


def dump_buttons(page: Page, name: str) -> None:
    data = page.locator("button[aria-label], [title], [role='button']").evaluate_all(
        """elements => elements.map((element, index) => {
            const box = element.getBoundingClientRect();
            return {
                index,
                tag: element.tagName,
                aria: element.getAttribute("aria-label"),
                title: element.getAttribute("title"),
                role: element.getAttribute("role"),
                text: (element.innerText || "").trim().replace(/\\s+/g, " ").slice(0, 120),
                visible: box.width > 0 && box.height > 0,
                rect: {
                    x: Math.round(box.x),
                    y: Math.round(box.y),
                    w: Math.round(box.width),
                    h: Math.round(box.height)
                }
            };
        }).filter(item => item.visible && (
            (item.aria || "").match(/Environmental|FEMA|Public|Property|Layer|Aerial/i) ||
            (item.title || "").match(/Environmental|FEMA|Public|Property|Layer|Aerial/i) ||
            (item.text || "").match(/Environmental|FEMA|Public|Property|Layer|Aerial/i)
        ))"""
    )
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


class DiagnosticRunner(EnvironmentalMapsRunner):
    def _prepare_environmental_map(self, page: Page) -> None:
        target_layers = ("FEMA 100-year Floodplain (1 PCT Annual Chance)", "FEMA 500-year Floodplain (0.2 PCT Annual Chance)")
        progress("DIAG before layer panel")
        shot(page, "10-before-layer-panel")
        self._close_popups(page)
        self._ensure_layer_manager_available(page)
        page.wait_for_timeout(700)
        progress("DIAG after layer panel")
        shot(page, "11-after-layer-panel")
        self._ensure_environmental_layers_visible(page)
        progress("DIAG after environmental")
        shot(page, "12-after-environmental")
        for index, layer_name in enumerate(target_layers, start=1):
            progress(f"DIAG before {layer_name}")
            shot(page, f"13-before-fema-{index}")
            self._set_layer_enabled(page, layer_name, True)
            page.wait_for_timeout(700)
            progress(f"DIAG after {layer_name}")
            shot(page, f"14-after-fema-{index}")


def main() -> int:
    OUT.mkdir(exist_ok=True)
    for path in OUT.glob("*"):
        if path.is_file():
            path.unlink()

    with sync_playwright() as playwright:
        runner = DiagnosticRunner(
            parcel_number=PARCEL,
            destination=OUT,
            progress=progress,
            stop_event=threading.Event(),
            environmental_group="FEMA Floodplain",
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
            runner._prepare_environmental_map(map_page)
            progress(f"DIAG saved to {OUT.resolve()}")
        finally:
            context.close()
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
