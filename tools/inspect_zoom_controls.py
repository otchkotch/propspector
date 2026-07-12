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
        map_page.wait_for_timeout(5_000)

        data = map_page.evaluate(
            """() => {
                const isVisible = (element) => {
                    const style = window.getComputedStyle(element);
                    const box = element.getBoundingClientRect();
                    return box.width > 0 && box.height > 0 && style.display !== "none" && style.visibility !== "hidden";
                };
                return [...document.querySelectorAll("button, [role='button'], [title], [aria-label], .esri-zoom *")]
                    .map((element, index) => {
                        const box = element.getBoundingClientRect();
                        return {
                            index,
                            tag: element.tagName,
                            className: String(element.className || ""),
                            title: element.getAttribute("title"),
                            ariaLabel: element.getAttribute("aria-label"),
                            role: element.getAttribute("role"),
                            text: (element.textContent || "").trim(),
                            x: Math.round(box.x),
                            y: Math.round(box.y),
                            width: Math.round(box.width),
                            height: Math.round(box.height),
                            visible: isVisible(element),
                        };
                    })
                    .filter((item) => {
                        const haystack = [
                            item.className,
                            item.title,
                            item.ariaLabel,
                            item.role,
                            item.text,
                        ].filter(Boolean).join(" ").toLowerCase();
                        return item.visible && (
                            haystack.includes("zoom") ||
                            item.text === "+" ||
                            item.text === "-"
                        );
                    });
            }"""
        )
        print(json.dumps(data, indent=2), flush=True)
        context.close()
        browser.close()


if __name__ == "__main__":
    main()
