from __future__ import annotations

import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parcel_packet.environmental_runner import EnvironmentalMapsRunner


def main() -> None:
    parcel = sys.argv[1] if len(sys.argv) > 1 else "1105400001"
    out = Path(f"_verify_popup_zoom_{parcel}")
    out.mkdir(exist_ok=True)
    runner = EnvironmentalMapsRunner(
        parcel_number=parcel,
        destination=out,
        progress=lambda message: print(message, flush=True),
        stop_event=threading.Event(),
        environmental_group="Forests NHD",
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
        map_page.screenshot(path=str(out / "01-map-open.png"), full_page=False)
        runner._close_map_popup(map_page)
        runner._wait_for_map_to_settle(map_page, timeout_ms=10_000)
        runner._close_map_popup(map_page)
        map_page.screenshot(path=str(out / "02-popup-close-attempt.png"), full_page=False)
        runner._fit_map_to_parcel_extent(map_page)
        map_page.screenshot(path=str(out / "03-after-fit-zoom.png"), full_page=False)
        context.close()
        browser.close()


if __name__ == "__main__":
    main()
