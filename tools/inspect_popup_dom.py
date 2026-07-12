from __future__ import annotations

import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parcel_packet.environmental_runner import EnvironmentalMapsRunner


def main() -> None:
    parcel = sys.argv[1] if len(sys.argv) > 1 else "2605000039"
    runner = EnvironmentalMapsRunner(
        parcel_number=parcel,
        destination=Path(f"_inspect_popup_{parcel}"),
        progress=lambda message: print(message, flush=True),
        stop_event=threading.Event(),
        environmental_group="FEMA Floodplain",
        pause_seconds=1,
        headless_browser=False,
        offscreen_browser=False,
    )
    runner._parcel_geometry = runner._get_parcel_geometry()

    with sync_playwright() as playwright:
        browser = runner._launch_browser(playwright)
        context = browser.new_context(viewport={"width": 1600, "height": 900}, device_scale_factor=2)
        page = context.new_page()
        page.set_default_timeout(30_000)
        runner._open_search(page)
        runner._search(page)
        runner._open_first_result(page)
        map_page = runner._open_map(page)
        runner._wait_for_map_to_settle(map_page, timeout_ms=10_000)
        runner._fit_map_to_parcel_extent(map_page)
        print(
            map_page.evaluate(
                """() => {
                    const visible = (element) => {
                        const style = getComputedStyle(element);
                        const box = element.getBoundingClientRect();
                        return box.width > 0 && box.height > 0 &&
                            style.display !== "none" &&
                            style.visibility !== "hidden" &&
                            Number(style.opacity || 1) > 0.05;
                    };
                    const describe = (element) => {
                        const box = element.getBoundingClientRect();
                        return {
                            tag: element.tagName,
                            id: element.id || "",
                            className: String(element.className || ""),
                            role: element.getAttribute("role") || "",
                            title: element.getAttribute("title") || "",
                            aria: element.getAttribute("aria-label") || "",
                            text: (element.innerText || element.textContent || "").replace(/\\s+/g, " ").slice(0, 180),
                            box: {
                                x: Math.round(box.x),
                                y: Math.round(box.y),
                                width: Math.round(box.width),
                                height: Math.round(box.height),
                            },
                        };
                    };
                    const hosts = [...document.querySelectorAll("*")]
                        .filter((element) => visible(element) && /Parcel ID:/i.test(element.innerText || element.textContent || ""))
                        .slice(0, 8);
                    return hosts.map((host) => {
                        const chain = [];
                        let node = host;
                        for (let i = 0; node && i < 10; i += 1) {
                            chain.push(describe(node));
                            node = node.parentElement;
                        }
                        return chain;
                    });
                }"""
            ),
            flush=True,
        )
        map_page.screenshot(path=str(runner.destination / "after-fit.png"), full_page=False)
        context.close()
        browser.close()


if __name__ == "__main__":
    main()
