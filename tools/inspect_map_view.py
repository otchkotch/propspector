from __future__ import annotations

import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parcel_packet.environmental_runner import EnvironmentalMapsRunner


def main() -> None:
    parcel = sys.argv[1] if len(sys.argv) > 1 else "2605000039"
    out = Path(f"_inspect_map_view_{parcel}")
    out.mkdir(exist_ok=True)
    runner = EnvironmentalMapsRunner(
        parcel_number=parcel,
        destination=out,
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
        map_page.screenshot(path=str(out / "01-open.png"), full_page=False)
        print(
            map_page.evaluate(
                """() => {
                    const summaries = [];
                    const seen = new WeakSet();
                    const queue = [];
                    const push = (value, path) => {
                        if (!value || (typeof value !== "object" && typeof value !== "function") || seen.has(value)) return;
                        seen.add(value);
                        queue.push({ value, path });
                    };
                    for (const key of Object.getOwnPropertyNames(window)) {
                        if (/arcgis|esri|jimu|map|view|widget|experience|exb|app/i.test(key)) {
                            try { push(window[key], `window.${key}`); } catch {}
                        }
                    }
                    const describe = (value, path) => {
                        const out = { path };
                        for (const key of ["zoom", "scale", "resolution", "stationary", "updating"]) {
                            try {
                                if (typeof value[key] !== "undefined") out[key] = value[key];
                            } catch {}
                        }
                        try { out.type = value.declaredClass || value.type || value.constructor?.name || ""; } catch {}
                        try { out.hasGoTo = typeof value.goTo === "function"; } catch {}
                        try { out.hasMap = !!value.map; } catch {}
                        try { out.hasExtent = !!value.extent; } catch {}
                        return out;
                    };
                    while (queue.length && summaries.length < 40) {
                        const { value, path } = queue.shift();
                        let isView = false;
                        try {
                            isView = typeof value.goTo === "function" &&
                                typeof value.zoom !== "undefined" &&
                                typeof value.scale !== "undefined";
                        } catch {}
                        if (isView) summaries.push(describe(value, path));
                        let keys = [];
                        try { keys = Object.keys(value).slice(0, 250); } catch {}
                        for (const key of keys) {
                            if (/arcgis|esri|jimu|map|view|widget|runtime|state|data|app|store|manager|controller/i.test(key)) {
                                try { push(value[key], `${path}.${key}`); } catch {}
                            }
                        }
                    }
                    return summaries;
                }"""
            ),
            flush=True,
        )
        context.close()
        browser.close()


if __name__ == "__main__":
    main()
