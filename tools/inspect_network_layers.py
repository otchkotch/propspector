from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parcel_packet.environmental_runner import EnvironmentalMapsRunner


def main() -> None:
    seen: list[str] = []

    def remember(url: str) -> None:
        if any(term in url.lower() for term in ("featureserver", "mapserver", "arcgis/rest", "query", "layers")):
            if url not in seen:
                seen.append(url)

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
        page.on("request", lambda request: remember(request.url))
        page.set_default_timeout(30_000)
        runner._open_search(page)
        runner._search(page)
        runner._open_first_result(page)
        map_page = runner._open_map(page)
        map_page.on("request", lambda request: remember(request.url))
        runner._prepare_aerial_base_for_environmental(map_page)
        runner._prepare_environmental_map(map_page)
        map_page.wait_for_timeout(5_000)
        print(json.dumps(seen, indent=2), flush=True)
        context.close()
        browser.close()


if __name__ == "__main__":
    main()
