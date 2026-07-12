from __future__ import annotations

import re
import threading
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from playwright.sync_api import Browser, Locator, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from .pdf_tools import image_to_full_bleed_pdf, safe_file_part


SEARCH_URL = "https://www3.newcastlede.gov/parcel/search/"
PARCEL_INPUT = "#ctl00_ctl00_ContentPlaceHolder1_ContentPlaceHolder1__TextBoxParcelNumber"
SEARCH_BUTTON = "#ctl00_ctl00_ContentPlaceHolder1_ContentPlaceHolder1__ButtonSearch"


@dataclass(frozen=True)
class LayerRecipe:
    name: str
    layers: tuple[str, ...]


LAYER_RECIPES: tuple[LayerRecipe, ...] = (
    LayerRecipe("Aerial", ()),
    LayerRecipe("NHD Swamp Marsh State Wetlands", ("NHD", "Swamp/Marsh", "State Wetlands")),
    LayerRecipe("Forests NHD", ("Forests", "NHD")),
    LayerRecipe("Critical Natural Areas Coastal Zone", ("Critical Natural Areas", "Coastal Zone")),
    LayerRecipe("FEMA", ("FEMA",)),
)

ENVIRONMENTAL_LAYER_NAMES = (
    "NHD",
    "Swamp/Marsh",
    "State Wetlands",
    "Forests",
    "Critical Natural Areas",
    "Coastal Zone",
    "FEMA",
    "Floodplain",
    "Wetlands",
)

AERIAL_LAYER_PATTERNS = (
    re.compile(r"aerial", re.I),
    re.compile(r"imagery", re.I),
    re.compile(r"ortho", re.I),
)


Progress = Callable[[str], None]
Checkpoint = Callable[[str], None]
LOGGER = logging.getLogger("parcel_packet.automation")


class AutomationStopped(Exception):
    pass


class ParcelPacketRunner:
    def __init__(
        self,
        parcel_number: str,
        destination: Path,
        project_prefix: str,
        progress: Progress,
        checkpoint: Checkpoint,
        stop_event: threading.Event,
        important_pause_seconds: int = 20,
        settle_pause_seconds: int = 5,
        assisted_layers: bool = True,
        browser_channel: str = "msedge",
    ) -> None:
        self.parcel_number = parcel_number.strip()
        self.search_parcel_number = self._parcel_for_search(self.parcel_number)
        self.destination = destination
        self.project_prefix = project_prefix.strip() or "TP"
        self.progress = progress
        self.checkpoint = checkpoint
        self.stop_event = stop_event
        self.important_pause_seconds = max(0, important_pause_seconds)
        self.settle_pause_seconds = max(1, settle_pause_seconds)
        self.assisted_layers = assisted_layers
        self.browser_channel = browser_channel
        self._temp_images: list[Path] = []

    def run(self) -> list[Path]:
        self.destination.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = self._launch_browser(p)
            page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
            page.set_default_timeout(45_000)
            try:
                self._search_parcel(page)
                self._open_first_result(page)
                outputs = [self._save_details_pdf(page)]
                page = self._open_map(page)
                self._prepare_map(page)
                for recipe in LAYER_RECIPES:
                    self._check_stop()
                    self._apply_recipe(page, recipe)
                    outputs.append(self._capture_recipe_pdf(page, recipe))
                return outputs
            finally:
                browser.close()
                self._cleanup_temp_images()

    def _launch_browser(self, playwright) -> Browser:
        self.progress("Opening a browser session")
        launch_options = {
            "headless": False,
            "slow_mo": 125,
            "args": ["--start-maximized", "--disable-blink-features=AutomationControlled"],
        }
        channel = self.browser_channel.strip()
        if channel:
            try:
                LOGGER.info("Launching browser channel=%s", channel)
                return playwright.chromium.launch(channel=channel, **launch_options)
            except Exception as exc:
                LOGGER.exception("Browser channel launch failed")
                self.progress(f"Could not open {channel}; trying packaged Chromium ({exc})")
        LOGGER.info("Launching bundled Chromium")
        return playwright.chromium.launch(**launch_options)

    def _important_pause(self, page: Page, label: str) -> None:
        self.progress(label)
        self._sleep(page, self.important_pause_seconds)

    def _settle(self, page: Page, label: str) -> None:
        self.progress(label)
        self._sleep(page, self.settle_pause_seconds)

    def _sleep(self, page: Page, seconds: int) -> None:
        for _ in range(max(0, seconds)):
            self._check_stop()
            page.wait_for_timeout(1000)

    def _check_stop(self) -> None:
        if self.stop_event.is_set():
            raise AutomationStopped("Run cancelled")

    def _search_parcel(self, page: Page) -> None:
        self.progress("Loading parcel search")
        LOGGER.info("Searching parcel display=%s search=%s", self.parcel_number, self.search_parcel_number)
        page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=90_000)
        self._important_pause(page, "Waiting for the search page to settle")
        self._wait_for_search_form(page)
        page.locator(PARCEL_INPUT).fill(self.search_parcel_number)
        self.progress("Parcel number entered")
        page.locator(SEARCH_BUTTON).click()
        page.wait_for_load_state("domcontentloaded", timeout=90_000)
        self._important_pause(page, "Waiting for search results")

    def _wait_for_search_form(self, page: Page) -> None:
        if page.locator(PARCEL_INPUT).count():
            return
        try:
            page.locator(PARCEL_INPUT).wait_for(timeout=60_000)
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(
                "The parcel search form did not load. If the browser is blank, close it and try again; "
                "the county site may have stalled before serving the form."
            ) from exc

    def _open_first_result(self, page: Page) -> None:
        self.progress("Opening the parcel detail result")
        result = self._first_result_link(page)
        if result is None:
            raise RuntimeError("No parcel result link was found after the search.")
        result.click()
        page.wait_for_load_state("domcontentloaded", timeout=90_000)
        self._important_pause(page, "Waiting for parcel detail page")

    def _first_result_link(self, page: Page) -> Locator | None:
        parcel_text = self.search_parcel_number
        dashed_text = self.parcel_number.replace("-", r"[-\s]?").replace(".", r"[.\s]?")
        candidates = [
            page.get_by_role("link", name=re.compile(re.escape(self.parcel_number), re.I)),
            page.get_by_role("link", name=re.compile(re.escape(self.search_parcel_number), re.I)),
            page.locator("[id*='GridViewResults'] a").filter(has_text=re.compile(parcel_text, re.I)),
            page.locator("[id*='GridViewResults'] a").filter(has_text=re.compile(dashed_text, re.I)),
            page.locator("[id*='GridViewResults'] a").first,
            page.locator("a").filter(has_text=re.compile(parcel_text, re.I)),
            page.locator("a").filter(has_text=re.compile(dashed_text, re.I)),
        ]
        for candidate in candidates:
            try:
                if candidate.count():
                    return candidate.first
            except Exception:
                continue
        return None

    def _save_details_pdf(self, page: Page) -> Path:
        self.progress("Saving parcel detail PDF")
        name = self._output_name("Parcel Details", suffix=".pdf")
        try:
            page.emulate_media(media="screen")
            page.pdf(path=str(name), print_background=True, format="Letter", margin={"top": "0.25in", "right": "0.25in", "bottom": "0.25in", "left": "0.25in"})
        except Exception:
            image_path = self._temp_image_path("Parcel Details")
            page.screenshot(path=str(image_path), full_page=True)
            image_to_full_bleed_pdf(image_path, name)
        return name

    def _open_map(self, page: Page) -> Page:
        self.progress("Opening map")
        link = self._find_clickable(page, ("view map", "map"))
        if link is None:
            raise RuntimeError("Could not find the View Map link on the parcel detail page.")
        popup = None
        try:
            with page.expect_popup(timeout=10_000) as popup_info:
                link.click()
            popup = popup_info.value
        except PlaywrightTimeoutError:
            pass
        if popup is not None:
            page = popup
        page.wait_for_load_state("domcontentloaded", timeout=90_000)
        self._important_pause(page, "Waiting for map to load")
        return page

    def _prepare_map(self, page: Page) -> None:
        self.progress("Preparing map view")
        self._close_known_popups(page)
        self._zoom_out_once(page)
        self._enable_aerial(page)
        self._close_known_popups(page)
        self._collapse_layer_manager(page)
        self._important_pause(page, "Letting the aerial map settle")

    def _find_clickable(self, page: Page, texts: tuple[str, ...]) -> Locator | None:
        for text in texts:
            locators = [
                page.get_by_role("link", name=re.compile(text, re.I)),
                page.get_by_role("button", name=re.compile(text, re.I)),
                page.locator("a, button").filter(has_text=re.compile(text, re.I)),
            ]
            for locator in locators:
                try:
                    if locator.count():
                        return locator.first
                except Exception:
                    continue
        return None

    def _close_known_popups(self, page: Page) -> None:
        for pattern in (r"close", r"x"):
            for role in ("button", "link"):
                try:
                    loc = getattr(page, f"get_by_role")(role, name=re.compile(pattern, re.I))
                    if loc.count():
                        loc.first.click(timeout=1500)
                except Exception:
                    pass

    def _zoom_out_once(self, page: Page) -> None:
        for selector in (".esriSimpleSliderDecrementButton", "[title='Zoom Out']", "button[aria-label*='Zoom out' i]"):
            try:
                loc = page.locator(selector).first
                if loc.count():
                    loc.click(timeout=3000)
                    self._settle(page, "Zoomed out one level")
                    return
            except Exception:
                continue
        self.progress("Zoom control was not exposed; continuing without automatic zoom")

    def _enable_aerial(self, page: Page) -> None:
        self.progress("Checking aerial imagery")
        for pattern in AERIAL_LAYER_PATTERNS:
            if self._set_layer_by_text(page, pattern, True):
                self._settle(page, "Aerial layer selected")
                return
        if self.assisted_layers:
            self.checkpoint(
                "Turn on the most recent aerial image, close the parcel info popup, "
                "and collapse the layer manager if needed. Then press Continue."
            )

    def _collapse_layer_manager(self, page: Page) -> None:
        for pattern in (r"layer", r"layers"):
            clickable = self._find_clickable(page, (pattern,))
            if clickable is not None:
                try:
                    clickable.click(timeout=2000)
                    return
                except Exception:
                    pass

    def _apply_recipe(self, page: Page, recipe: LayerRecipe) -> None:
        if recipe.name == "Aerial":
            self._close_known_popups(page)
            self._important_pause(page, "Capturing aerial map")
            return
        self.progress(f"Preparing {recipe.name}")
        automated = self._reset_environmental_layers(page)
        for layer_name in recipe.layers:
            automated = self._set_layer_by_text(page, re.compile(re.escape(layer_name), re.I), True) and automated
        self._close_known_popups(page)
        self._collapse_layer_manager(page)
        if self.assisted_layers:
            note = (
                f"Confirm this layer grouping is visible: {recipe.name}. "
                "Keep the aerial image on, and make sure unrelated environmental layers are off. "
                "Then press Continue."
            )
            if not automated:
                note = "Automatic layer selection was incomplete. " + note
            self.checkpoint(note)
        self._important_pause(page, f"Letting {recipe.name} settle")

    def _reset_environmental_layers(self, page: Page) -> bool:
        ok = True
        for name in ENVIRONMENTAL_LAYER_NAMES:
            ok = self._set_layer_by_text(page, re.compile(re.escape(name), re.I), False) and ok
        return ok

    def _set_layer_by_text(self, page: Page, pattern: re.Pattern[str], enabled: bool) -> bool:
        try:
            labels = page.locator("label").filter(has_text=pattern)
            if labels.count():
                label = labels.first
                checkbox = self._checkbox_near_label(label)
                if checkbox is not None:
                    checked = checkbox.is_checked(timeout=1500)
                    if checked != enabled:
                        checkbox.click(timeout=3000)
                    return True
                label.click(timeout=3000)
                return True
        except Exception:
            pass
        return False

    def _checkbox_near_label(self, label: Locator) -> Locator | None:
        for selector in (
            "xpath=preceding::input[@type='checkbox'][1]",
            "xpath=following::input[@type='checkbox'][1]",
            "xpath=ancestor::*[self::li or self::tr or self::div][1]//input[@type='checkbox']",
        ):
            try:
                checkbox = label.locator(selector).first
                if checkbox.count():
                    return checkbox
            except Exception:
                continue
        return None

    def _capture_recipe_pdf(self, page: Page, recipe: LayerRecipe) -> Path:
        self.progress(f"Saving {recipe.name} PDF")
        image_path = self._temp_image_path(recipe.name)
        pdf_path = self._output_name(f"{recipe.name} Map", suffix=".pdf")
        page.screenshot(path=str(image_path), full_page=False)
        image_to_full_bleed_pdf(image_path, pdf_path)
        return pdf_path

    def _output_name(self, middle: str, suffix: str) -> Path:
        filename = f"{safe_file_part(self.project_prefix)} {safe_file_part(self.parcel_number)} {safe_file_part(middle)}{suffix}"
        return self.destination / filename

    def _temp_image_path(self, middle: str) -> Path:
        path = self.destination / f".{safe_file_part(self.parcel_number)} {safe_file_part(middle)}.png"
        self._temp_images.append(path)
        return path

    def _cleanup_temp_images(self) -> None:
        for path in self._temp_images:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def _parcel_for_search(self, parcel_number: str) -> str:
        return "".join(ch for ch in parcel_number if ch.isalnum())
