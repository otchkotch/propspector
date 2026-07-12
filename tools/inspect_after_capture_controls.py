from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parcel_packet.environmental_runner import EnvironmentalMapsRunner


def main() -> None:
    runner = EnvironmentalMapsRunner(
        parcel_number="2605000039",
        destination=Path("_codex_visible_check"),
        progress=lambda message: print(message, flush=True),
        stop_event=threading.Event(),
        environmental_group="NHD Swamp Marsh State Wetlands",
        pause_seconds=1,
        headless_browser=False,
        offscreen_browser=False,
    )
    with sync_playwright() as playwright:
        browser = runner._launch_browser(playwright)
        context = browser.new_context(viewport={"width": 1600, "height": 900}, device_scale_factor=2)
        page = context.new_page()
        page.set_default_timeout(30_000)
        runner._open_search(page)
        runner._search(page)
        runner._open_first_result(page)
        map_page = runner._open_map(page)
        runner._prepare_aerial_base_for_environmental(map_page)
        runner._prepare_environmental_map(map_page, "NHD Swamp Marsh State Wetlands")
        runner._capture_current_map_pdf(map_page, "NHD Swamp Marsh State Wetlands Map", "inspect-after-first-capture")
        map_page.wait_for_timeout(1_000)
        controls = map_page.evaluate(
            """() => {
                const isVisible = (element) => {
                    const style = window.getComputedStyle(element);
                    const box = element.getBoundingClientRect();
                    return box.width > 0 && box.height > 0 &&
                        style.display !== "none" && style.visibility !== "hidden";
                };
                return [...document.querySelectorAll("button, [role='button'], [title], [aria-label], calcite-action, img, div")]
                    .map((element, index) => {
                        const box = element.getBoundingClientRect();
                        return {
                            index,
                            tag: element.tagName,
                            className: String(element.className || ""),
                            title: element.getAttribute("title"),
                            aria: element.getAttribute("aria-label"),
                            role: element.getAttribute("role"),
                            alt: element.getAttribute("alt"),
                            src: element.getAttribute("src"),
                            text: (element.textContent || "").trim().replace(/\\s+/g, " ").slice(0, 120),
                            x: Math.round(box.x),
                            y: Math.round(box.y),
                            width: Math.round(box.width),
                            height: Math.round(box.height),
                        };
                    })
                    .filter((item) => {
                        if (item.width <= 0 || item.height <= 0) return false;
                        const haystack = [item.className, item.title, item.aria, item.role, item.alt, item.src, item.text]
                            .filter(Boolean).join(" ").toLowerCase();
                        return item.y < 120 || item.x > window.innerWidth * 0.75 ||
                            /layer|legend|environmental|collapse|expand|close|list/.test(haystack);
                    })
                    .slice(0, 250);
            }"""
        )
        print(json.dumps(controls, indent=2), flush=True)
        context.close()
        browser.close()


if __name__ == "__main__":
    main()
