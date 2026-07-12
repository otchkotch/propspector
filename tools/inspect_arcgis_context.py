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
        runner._prepare_aerial_base_for_environmental(map_page)
        runner._ensure_layer_manager_available(map_page)
        runner._ensure_environmental_layers_visible(map_page)
        runner._expand_environmental_sublayers(map_page)
        map_page.wait_for_timeout(1_000)

        data = map_page.evaluate(
            """async () => {
                const seen = new Set();
                const views = [];
                const inspect = (value, path, depth = 0) => {
                    if (!value || typeof value !== "object" || seen.has(value) || depth > 4) return;
                    seen.add(value);
                    try {
                        const candidate = {
                            path,
                            type: value.type,
                            declaredClass: value.declaredClass,
                            hasMap: !!value.map,
                            hasViewpoint: !!value.viewpoint,
                            hasExtent: !!value.extent,
                            hasGraphics: !!value.graphics,
                            hasLayerViews: !!value.layerViews,
                            layerCount: value.map?.layers?.length,
                            allLayerCount: value.map?.allLayers?.length,
                            popupTitle: value.popup?.title,
                        };
                        if (candidate.hasMap || candidate.hasViewpoint || candidate.hasLayerViews || candidate.declaredClass?.includes("View")) {
                            views.push(candidate);
                        }
                    } catch {}
                    const keys = Object.keys(value).slice(0, 80);
                    for (const key of keys) {
                        if (/view|map|jimu|widget|arcgis|experience|app/i.test(key)) {
                            try { inspect(value[key], `${path}.${key}`, depth + 1); } catch {}
                        }
                    }
                };
                inspect(window, "window");
                const layerRows = [...document.querySelectorAll("calcite-list-item[title], [role='row'][aria-label], button[aria-label]")]
                    .map((element) => ({
                        tag: element.tagName,
                        title: element.getAttribute("title"),
                        aria: element.getAttribute("aria-label"),
                        text: (element.textContent || "").trim().replace(/\\s+/g, " ").slice(0, 120),
                    }))
                    .filter((item) => /Environmental|FEMA|Flood|Wetland|Swamp|Forest|Critical|Coastal|NHD|WRPA/i.test([item.title, item.aria, item.text].join(" ")));
                return { views: views.slice(0, 60), layerRows: layerRows.slice(0, 120) };
            }"""
        )
        print(json.dumps(data, indent=2), flush=True)
        context.close()
        browser.close()


if __name__ == "__main__":
    main()
