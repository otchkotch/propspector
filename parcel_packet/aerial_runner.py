from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from playwright.sync_api import Browser, Locator, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from .pdf_tools import image_to_full_bleed_pdf, safe_file_part


SEARCH_URL = "https://www3.newcastlede.gov/parcel/search/"
PARCEL_INPUT = "#ctl00_ctl00_ContentPlaceHolder1_ContentPlaceHolder1__TextBoxParcelNumber"
SEARCH_BUTTON = "#ctl00_ctl00_ContentPlaceHolder1_ContentPlaceHolder1__ButtonSearch"

LOGGER = logging.getLogger("parcel_packet.aerial_runner")
Progress = Callable[[str], None]


@dataclass(frozen=True)
class AerialResult:
    image_path: Path
    pdf_path: Path
    debug_folder: Path


class AerialMapRunner:
    def __init__(
        self,
        parcel_number: str,
        destination: Path,
        progress: Progress,
        stop_event: threading.Event,
        pause_seconds: int = 3,
        browser_channel: str = "msedge",
        headless_browser: bool = False,
        offscreen_browser: bool = False,
    ) -> None:
        self.parcel_number = parcel_number.strip()
        self.search_parcel_number = self._parcel_for_search(self.parcel_number)
        self.destination = destination
        self.progress = progress
        self.stop_event = stop_event
        self.pause_seconds = max(1, min(5, pause_seconds))
        self.browser_channel = browser_channel
        self.headless_browser = headless_browser
        self.offscreen_browser = offscreen_browser
        self.debug_folder = self.destination / "_debug_aerial"

    def run(self) -> AerialResult:
        self.destination.mkdir(parents=True, exist_ok=True)
        self.debug_folder.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = self._launch_browser(playwright)
            context = browser.new_context(
                viewport={"width": 1600, "height": 900},
                device_scale_factor=2,
            )
            page = context.new_page()
            page.set_default_timeout(30_000)
            try:
                self._open_search(page)
                self._search(page)
                self._open_first_result(page)
                map_page = self._open_map(page)
                self._prepare_aerial_map(map_page)
                image_path = self._output_path("Aerial Map", ".png")
                pdf_path = self._output_path("Aerial Map", ".pdf")
                self.progress("Saving aerial screenshot")
                self._close_popups(map_page)
                self._pause(map_page)
                map_page.screenshot(path=str(image_path), full_page=False)
                image_to_full_bleed_pdf(image_path, pdf_path)
                self._debug_screenshot(map_page, "06-final-aerial")
                self._cleanup_success_images(image_path)
                return AerialResult(image_path=image_path, pdf_path=pdf_path, debug_folder=self.debug_folder)
            finally:
                context.close()
                browser.close()

    def _launch_browser(self, playwright) -> Browser:
        options = {
            "headless": self.headless_browser,
            "slow_mo": 20,
            "args": [
                "--window-size=1640,980",
                "--disable-blink-features=AutomationControlled",
            ],
        }
        if self.offscreen_browser and not self.headless_browser:
            options["args"].append("--window-position=-32000,-32000")
        if self.browser_channel:
            try:
                LOGGER.info("Launching %s", self.browser_channel)
                return playwright.chromium.launch(channel=self.browser_channel, **options)
            except Exception:
                LOGGER.exception("Preferred browser launch failed; falling back to bundled Chromium")
        return playwright.chromium.launch(**options)

    def _open_search(self, page: Page) -> None:
        self.progress("Opening parcel search")
        page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=60_000)
        self._pause(page)
        self._debug_screenshot(page, "01-search")
        page.locator(PARCEL_INPUT).wait_for(timeout=30_000)

    def _search(self, page: Page) -> None:
        self.progress(f"Searching parcel {self.search_parcel_number}")
        page.locator(PARCEL_INPUT).fill(self.search_parcel_number)
        page.locator(SEARCH_BUTTON).click()
        page.wait_for_load_state("domcontentloaded", timeout=60_000)
        self._pause(page)
        self._debug_screenshot(page, "02-results")

    def _open_first_result(self, page: Page) -> None:
        self.progress("Opening first parcel result")
        result = self._first_result_link(page)
        if result is None:
            raise RuntimeError("No parcel result link was found. Check the debug screenshot named 02-results.")
        result.click()
        page.wait_for_load_state("domcontentloaded", timeout=60_000)
        self._pause(page)
        self._debug_screenshot(page, "03-detail")

    def _first_result_link(self, page: Page) -> Locator | None:
        dashed_text = self.parcel_number.replace("-", r"[-\s]?").replace(".", r"[.\s]?")
        candidates = [
            page.locator("[id*='GridViewResults'] a").filter(has_text=re.compile(self.search_parcel_number, re.I)),
            page.locator("[id*='GridViewResults'] a").filter(has_text=re.compile(dashed_text, re.I)),
            page.locator("[id*='GridViewResults'] a").first,
            page.get_by_role("link", name=re.compile(self.search_parcel_number, re.I)),
            page.get_by_role("link", name=re.compile(dashed_text, re.I)),
        ]
        for candidate in candidates:
            try:
                if candidate.count():
                    return candidate.first
            except Exception:
                continue
        return None

    def _open_map(self, page: Page) -> Page:
        self.progress("Opening map")
        link = self._find_clickable(page, (r"view map",))
        if link is None:
            link = self._find_clickable(page, (r"\bmap\b",))
        if link is None:
            raise RuntimeError("Could not find the View Map link. Check the debug screenshot named 03-detail.")

        try:
            with page.expect_popup(timeout=5_000) as popup_info:
                link.click()
            map_page = popup_info.value
        except PlaywrightTimeoutError:
            link.click()
            map_page = page

        map_page.wait_for_load_state("domcontentloaded", timeout=60_000)
        self._pause(map_page)
        self._debug_screenshot(map_page, "04-map-loaded")
        return map_page

    def _prepare_aerial_map(self, page: Page) -> None:
        self.progress("Preparing aerial map")
        self._close_popups(page)
        self._zoom_out_once(page)
        self._close_popups(page)
        self._turn_on_aerial(page)
        self._close_popups(page)
        self._collapse_panels(page)
        self._pause(page)
        self._debug_screenshot(page, "05-aerial-ready")

    def _turn_on_aerial(self, page: Page) -> None:
        self.progress("Turning on aerial image")
        self._close_popups(page)
        if self._enable_newest_aerial_imagery(page):
            self._pause(page)
            return
        self._debug_screenshot(page, "05-aerial-layer-not-found")
        raise RuntimeError("Could not find the NCC Aerial Imagery visibility button.")

    def _enable_newest_aerial_imagery(self, page: Page) -> bool:
        self._ensure_base_layers_visible(page)
        buttons = page.locator("button[aria-label*='NCC Aerial Imagery']")
        try:
            labels = buttons.evaluate_all(
                """els => els.map((button, index) => ({
                    index,
                    label: button.getAttribute("aria-label") || "",
                    visible: !!(button.getBoundingClientRect().width && button.getBoundingClientRect().height)
                }))"""
            )
        except Exception:
            LOGGER.exception("Could not inspect NCC Aerial Imagery buttons")
            return False

        candidates: list[tuple[int, int, str, bool]] = []
        for item in labels:
            match = re.match(r"^(Show|Hide)\s+(\d{4})\s+NCC Aerial Imagery$", item["label"], re.I)
            if match:
                candidates.append((int(match.group(2)), int(item["index"]), item["label"], bool(item["visible"])))

        if not candidates:
            LOGGER.info("No exact NCC Aerial Imagery aria-label button found; inspected labels=%s", labels)
            return False

        year, index, label, visible = max(candidates, key=lambda value: value[0])
        LOGGER.info("Selected newest aerial imagery button year=%s index=%s visible=%s label=%s", year, index, visible, label)
        target = buttons.nth(index)
        target.scroll_into_view_if_needed(timeout=5_000)
        if label.lower().startswith("show "):
            target.click(timeout=5_000)
        else:
            LOGGER.info("Newest aerial imagery is already enabled")
        page.wait_for_timeout(1000)
        return True

    def _ensure_base_layers_visible(self, page: Page) -> None:
        if page.locator("button[aria-label*='NCC Aerial Imagery']").count():
            return
        self._open_layer_panel(page)
        page.wait_for_timeout(500)
        if page.locator("button[aria-label*='NCC Aerial Imagery']").count():
            return
        for selector in (
            "button[aria-label*='Base Layers' i]",
            "text=Base Layers",
        ):
            try:
                target = page.locator(selector).first
                if target.count():
                    LOGGER.info("Expanding Base Layers with selector=%s", selector)
                    target.click(timeout=2_500)
                    page.wait_for_timeout(500)
                    return
            except Exception:
                continue

    def _open_layer_panel(self, page: Page) -> bool:
        selectors = (
            "[title*='Layer' i]",
            "[aria-label*='Layer' i]",
            ".jimu-icon-layer-list",
            ".jimu-icon-layers",
        )
        for selector in selectors:
            try:
                controls = page.locator(selector)
                if controls.count():
                    LOGGER.info("Opening layer panel with selector=%s count=%s", selector, controls.count())
                    controls.first.click(timeout=2_500)
                    return True
            except Exception:
                continue
        try:
            size = page.viewport_size or {"width": 1600, "height": 900}
            LOGGER.info("Opening layer panel by toolbar fallback; viewport=%s", size)
            page.mouse.click(size["width"] - 22, 22)
            return True
        except Exception:
            LOGGER.exception("Could not open layer panel")
            return False

    def _click_jimu_aerial_checkbox(self, page: Page) -> bool:
        selector = ".checkbox.jimu-float-leading.jimu-icon.jimu-icon-checkbox"
        try:
            aerial_rows = page.locator(
                "xpath=//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'aerial') "
                "or contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'imagery') "
                "or contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'ortho')]"
            )
            for index in range(min(aerial_rows.count(), 20)):
                row = aerial_rows.nth(index)
                checkbox = row.locator(selector).first
                if checkbox.count() and checkbox.is_visible(timeout=500):
                    LOGGER.info("Clicking Jimu aerial checkbox within aerial/imagery row index=%s", index)
                    checkbox.click(timeout=2_500)
                    return True
        except Exception:
            LOGGER.exception("Could not click row-scoped Jimu aerial checkbox")

        try:
            checkboxes = page.locator(selector)
            visible_count = 0
            for index in range(checkboxes.count()):
                checkbox = checkboxes.nth(index)
                if checkbox.is_visible(timeout=500):
                    visible_count += 1
                    LOGGER.info("Clicking first visible Jimu checkbox index=%s visible_count=%s", index, visible_count)
                    checkbox.click(timeout=2_500)
                    return True
            LOGGER.info("No visible Jimu checkbox found; total count=%s", checkboxes.count())
        except Exception:
            LOGGER.exception("Could not click visible Jimu checkbox")
        return False

    def _open_basemap_gallery_from_toolbar(self, reason: str) -> bool:
        try:
            size = page.viewport_size or {"width": 3840, "height": 2160}
            LOGGER.info("Opening basemap gallery by %s; viewport=%s", reason, size)
            # Current NCC toolbar order places the four-tile basemap button just
            # left of the share/print/layer tools. Keep this as a last resort.
            page.mouse.click(size["width"] - 136, 22)
            return True
        except Exception:
            LOGGER.exception("Could not click basemap toolbar fallback")
            return False

    def _zoom_out_once(self, page: Page) -> None:
        self.progress("Zooming out one level")
        elapsed = 0
        step = 250
        while elapsed <= 8_000:
            if self.stop_event.is_set():
                raise RuntimeError("Run cancelled")
            try:
                handle = page.evaluate_handle(
                    """() => {
                        const isVisible = (element) => {
                            const style = window.getComputedStyle(element);
                            const box = element.getBoundingClientRect();
                            return (
                                box.width > 0 &&
                                box.height > 0 &&
                                style.display !== "none" &&
                                style.visibility !== "hidden" &&
                                Number(style.opacity || 1) > 0.05
                            );
                        };

                        const candidates = [...document.querySelectorAll("button, [role='button'], [title], [aria-label]")];
                        return candidates.find((element) => {
                            const label = [
                                element.getAttribute("aria-label"),
                                element.getAttribute("title"),
                                element.textContent,
                            ].filter(Boolean).join(" ").toLowerCase();
                            return isVisible(element) && label.includes("zoom out");
                        }) || null;
                    }"""
                )
                control = handle.as_element()
                if control is not None:
                    actual_label = " ".join(
                        value
                        for value in (
                            control.get_attribute("aria-label"),
                            control.get_attribute("title"),
                        )
                        if value
                    )
                    LOGGER.info("Clicking verified zoom-out control label=%s", actual_label)
                    control.click(timeout=2_000)
                    self._pause(page)
                    return
            except Exception:
                LOGGER.exception("Could not click verified zoom-out control")

            try:
                zoom_box = page.evaluate(
                    """() => {
                        const isVisible = (element) => {
                            const style = window.getComputedStyle(element);
                            const box = element.getBoundingClientRect();
                            return (
                                box.width > 0 &&
                                box.height > 0 &&
                                style.display !== "none" &&
                                style.visibility !== "hidden" &&
                                Number(style.opacity || 1) > 0.05
                            );
                        };
                        const shell = [...document.querySelectorAll(".exbmap-ui-tool-shell-Zoom, [class*='tool-shell-Zoom']")]
                            .find(isVisible);
                        if (!shell) {
                            return null;
                        }
                        const box = shell.getBoundingClientRect();
                        return {
                            x: box.x + box.width / 2,
                            y: box.y + box.height * 0.75,
                        };
                    }"""
                )
                if zoom_box:
                    LOGGER.info("Clicking lower half of zoom widget at x=%s y=%s", zoom_box["x"], zoom_box["y"])
                    page.mouse.click(zoom_box["x"], zoom_box["y"])
                    self._pause(page)
                    return
            except Exception:
                LOGGER.exception("Could not click zoom widget lower half")

            page.wait_for_timeout(step)
            elapsed += step
        self.progress("Zoom-out button was not exposed; continuing at default zoom")

    def _close_popups(self, page: Page) -> None:
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(150)
        except Exception:
            pass
        for selector in (
            ".titleButton.close",
            ".esri-popup__button[title='Close']",
            ".esri-popup__button--close",
            ".esri-popup__header-buttons .esri-popup__button",
            ".esri-popup__icon--close",
            ".esri-popup__main-container [title='Close']",
            ".esriPopup .titleButton.close",
            "button[aria-label='Close']",
            "button[title='Close']",
            "[title='Close']",
            "[aria-label='Close']",
            ".close",
        ):
            try:
                controls = page.locator(selector)
                for index in range(min(controls.count(), 3)):
                    controls.nth(index).click(timeout=1_000)
            except Exception:
                continue
        self._close_parcel_popup_by_geometry(page)

    def _close_parcel_popup_by_geometry(self, page: Page) -> None:
        LOGGER.info("Skipping geometry-based popup close to avoid selecting map features")

    def _collapse_panels(self, page: Page) -> None:
        for pattern in (r"collapse",):
            try:
                control = self._find_clickable(page, (pattern,))
                if control is not None:
                    control.click(timeout=1_500)
                    return
            except Exception:
                continue

    def _click_matching_control(self, page: Page, patterns: tuple[str, ...]) -> bool:
        for pattern in patterns:
            regex = re.compile(pattern, re.I)
            locators = [
                page.get_by_role("button", name=regex),
                page.get_by_role("link", name=regex),
                page.locator("label").filter(has_text=regex),
                page.locator(f"[title*='{pattern}' i]"),
                page.locator(f"[aria-label*='{pattern}' i]"),
                page.locator(f"[alt*='{pattern}' i]"),
                page.locator("button, a, label, div[role='button'], span").filter(has_text=regex),
            ]
            for locator in locators:
                try:
                    if locator.count():
                        LOGGER.info("Clicking control for pattern=%s count=%s", pattern, locator.count())
                        locator.first.click(timeout=2_500)
                        return True
                except Exception:
                    continue
        return False

    def _find_clickable(self, page: Page, patterns: tuple[str, ...]) -> Locator | None:
        for pattern in patterns:
            regex = re.compile(pattern, re.I)
            locators = [
                page.get_by_role("link", name=regex),
                page.get_by_role("button", name=regex),
                page.locator("a, button, input[type='button'], input[type='submit']").filter(has_text=regex),
                page.locator(f"[value*='{pattern}' i]"),
                page.locator(f"[title*='{pattern}' i]"),
            ]
            for locator in locators:
                try:
                    if locator.count():
                        return locator.first
                except Exception:
                    continue
        return None

    def _pause(self, page: Page) -> None:
        for _ in range(self.pause_seconds):
            if self.stop_event.is_set():
                raise RuntimeError("Run cancelled")
            page.wait_for_timeout(1000)

    def _debug_screenshot(self, page: Page, name: str) -> None:
        try:
            page.screenshot(path=str(self.debug_folder / f"{name}.png"), full_page=False)
        except Exception:
            LOGGER.exception("Could not save debug screenshot %s", name)

    def _cleanup_success_images(self, output_image_path: Path) -> None:
        for image_path in self.destination.glob("*.png"):
            if image_path == output_image_path:
                try:
                    image_path.unlink()
                except OSError:
                    LOGGER.exception("Could not delete temporary image %s", image_path)
        for pattern in ("*.png", "*.jpg", "*.jpeg", "*.tif", "*.tiff"):
            for image_path in self.debug_folder.glob(pattern):
                try:
                    image_path.unlink()
                except OSError:
                    LOGGER.exception("Could not delete debug image %s", image_path)
        try:
            if self.debug_folder.exists() and not any(self.debug_folder.iterdir()):
                self.debug_folder.rmdir()
        except OSError:
            LOGGER.exception("Could not remove empty debug folder")

    def _output_path(self, middle: str, suffix: str) -> Path:
        filename = f"{safe_file_part(self.parcel_number)} {safe_file_part(middle)}{suffix}"
        return self.destination / filename

    def _parcel_for_search(self, parcel_number: str) -> str:
        return "".join(ch for ch in parcel_number if ch.isalnum())
