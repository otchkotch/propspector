from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import urllib.parse
import urllib.request

from playwright.sync_api import Page, sync_playwright

from .aerial_runner import AerialMapRunner, Progress
from .environmental_config import (
    ALL_RESOURCES_GROUP,
    ENVIRONMENTAL_GROUPS,
    ENVIRONMENTAL_LAYER_IDS,
    ENVIRONMENTAL_LAYER_SOURCES,
    ENVIRONMENTAL_LAYERS,
    ENVIRONMENTAL_MAPSERVER_URL,
    ENVIRONMENTAL_MENU_GROUPS,
    FEMA_LEGEND_PATH,
    PARCEL_LAYER_QUERY_URL,
    ResourcePresence,
    RESOURCE_STATUS_ORDER,
)
from .pdf_tools import image_to_full_bleed_pdf, images_to_full_bleed_pdf, safe_file_part


LOGGER = logging.getLogger("parcel_packet.environmental_runner")


ResourcePresenceCallback = Callable[[tuple[ResourcePresence, ...]], None]


@dataclass(frozen=True)
class EnvironmentalResult:
    environmental_pdf_paths: tuple[Path, ...]
    resource_statuses: tuple[ResourcePresence, ...]
    debug_folder: Path
    combined_pdf_path: Path | None = None

    @property
    def environmental_pdf_path(self) -> Path:
        return self.environmental_pdf_paths[0]


class EnvironmentalMapsRunner(AerialMapRunner):
    def __init__(
        self,
        parcel_number: str,
        destination: Path,
        progress: Progress,
        stop_event: threading.Event,
        environmental_group: str = ALL_RESOURCES_GROUP,
        pause_seconds: int = 3,
        browser_channel: str = "msedge",
        headless_browser: bool = False,
        offscreen_browser: bool = False,
        resource_status_callback: ResourcePresenceCallback | None = None,
    ) -> None:
        super().__init__(
            parcel_number=parcel_number,
            destination=destination,
            progress=progress,
            stop_event=stop_event,
            pause_seconds=pause_seconds,
            browser_channel=browser_channel,
            headless_browser=headless_browser,
            offscreen_browser=offscreen_browser,
        )
        self.environmental_group = environmental_group
        self.debug_folder = self.destination / "_debug_environmental"
        self._environmental_parent_enabled = False
        self._parcel_geometry: dict | None = None
        self.resource_status_callback = resource_status_callback

    def run(self) -> EnvironmentalResult:
        self.destination.mkdir(parents=True, exist_ok=True)
        self.debug_folder.mkdir(parents=True, exist_ok=True)
        selected_groups = self._selected_groups()
        self._parcel_geometry = self._get_parcel_geometry()
        resource_statuses = self._check_resource_presence()
        if self.resource_status_callback:
            self.resource_status_callback(resource_statuses)
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

                self._close_map_popup(map_page)
                self._fit_map_to_parcel_extent(map_page)
                self._prepare_aerial_base_for_environmental(map_page)
                environmental_pdf_paths: list[Path] = []
                captured_image_pages: list[tuple[Path, Path | None]] = []
                try:
                    for index, group_name in enumerate(selected_groups, start=1):
                        self._prepare_environmental_map(map_page, group_name)
                        pdf_path, image_path, legend_path = self._capture_current_map_pdf(
                            map_page,
                            f"{group_name} Map",
                            f"06-final-environmental-{index}",
                        )
                        environmental_pdf_paths.append(pdf_path)
                        captured_image_pages.append((image_path, legend_path))
                        if index < len(selected_groups):
                            self._reopen_layer_manager_after_capture(map_page)

                    combined_pdf_path = self._create_combined_environmental_pdf(captured_image_pages)
                    environmental_pdf_paths.append(combined_pdf_path)
                finally:
                    for image_path, _ in captured_image_pages:
                        try:
                            image_path.unlink(missing_ok=True)
                        except OSError:
                            LOGGER.exception("Could not delete temporary image %s", image_path)

                self._cleanup_success_images(self.destination / "__environmental_temp__.png")
                return EnvironmentalResult(
                    environmental_pdf_paths=tuple(environmental_pdf_paths),
                    resource_statuses=resource_statuses,
                    debug_folder=self.debug_folder,
                    combined_pdf_path=combined_pdf_path,
                )
            finally:
                context.close()
                browser.close()

    def _selected_groups(self) -> tuple[str, ...]:
        if self.environmental_group == ALL_RESOURCES_GROUP:
            return tuple(ENVIRONMENTAL_GROUPS.keys())
        if self.environmental_group not in ENVIRONMENTAL_GROUPS:
            raise RuntimeError(f"Unknown environmental layer group: {self.environmental_group}")
        return (self.environmental_group,)

    def _check_resource_presence(self) -> tuple[ResourcePresence, ...]:
        self.progress("Checking environmental resources")
        try:
            parcel_geometry = self._get_parcel_geometry()
        except Exception as exc:
            LOGGER.exception("Could not fetch parcel geometry for environmental presence checks")
            return tuple(ResourcePresence(name=name, status="Unknown", error=str(exc)) for name in RESOURCE_STATUS_ORDER)

        statuses: list[ResourcePresence] = []
        for name in RESOURCE_STATUS_ORDER:
            layer = ENVIRONMENTAL_LAYER_SOURCES.get(name)
            if layer is None:
                statuses.append(ResourcePresence(name=name, status="Unknown", error="No query layer mapped"))
                continue
            try:
                count = self._query_intersection_count(layer.mapserver_url, layer.layer_id, parcel_geometry)
                statuses.append(ResourcePresence(name=name, status="Present" if count > 0 else "Absent", count=count))
            except Exception as exc:
                LOGGER.exception("Could not check environmental presence for %s", name)
                statuses.append(ResourcePresence(name=name, status="Unknown", error=str(exc)))
        return tuple(statuses)

    def _get_parcel_geometry(self) -> dict:
        if self._parcel_geometry is None:
            self._parcel_geometry = self._fetch_parcel_geometry()
        return self._parcel_geometry

    def _fetch_parcel_geometry(self) -> dict:
        self.progress("Checking parcel geometry")
        data = self._fetch_json(
            PARCEL_LAYER_QUERY_URL,
            {
                "f": "json",
                "where": f"PARCELNO='{self.search_parcel_number}'",
                "outFields": "PARCELNO",
                "returnGeometry": "true",
                "outSR": "102100",
            },
        )
        features = data.get("features") or []
        if not features:
            raise RuntimeError("Parcel geometry was not found in the GIS service.")
        return features[0]["geometry"]

    def _query_intersection_count(self, mapserver_url: str, layer_id: int, parcel_geometry: dict) -> int:
        data = self._fetch_json(
            f"{mapserver_url}/{layer_id}/query",
            {
                "f": "json",
                "where": "1=1",
                "returnCountOnly": "true",
                "geometry": json.dumps(parcel_geometry, separators=(",", ":")),
                "geometryType": "esriGeometryPolygon",
                "inSR": "102100",
                "spatialRel": "esriSpatialRelIntersects",
            },
        )
        return int(data.get("count", 0))

    def _fetch_json(self, url: str, params: dict[str, str]) -> dict:
        encoded = urllib.parse.urlencode(params).encode("utf-8")
        request = urllib.request.Request(url, data=encoded, method="POST")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    def _fit_map_to_parcel_extent(self, page: Page) -> None:
        self.progress("Fitting map to parcel")
        self._close_map_popup(page)
        self._wait_for_map_to_settle(page, timeout_ms=10_000)
        self._close_map_popup(page)
        try:
            extent = self._parcel_extent_102100()
            fitted = page.evaluate(
                """async (extent) => {
                    const seen = new Set();
                    const candidates = [];
                    const inspect = (value, depth = 0) => {
                        if (!value || typeof value !== "object" || seen.has(value) || depth > 5) {
                            return;
                        }
                        seen.add(value);
                        try {
                            if (value.map && typeof value.goTo === "function" && value.extent) {
                                candidates.push(value);
                            }
                        } catch {}
                        for (const key of Object.keys(value).slice(0, 120)) {
                            if (/view|map|jimu|arcgis|widget|runtime|app/i.test(key)) {
                                try { inspect(value[key], depth + 1); } catch {}
                            }
                        }
                    };
                    inspect(window);
                    const view = candidates[0];
                    if (!view) {
                        return false;
                    }
                    const width = Math.max(extent.xmax - extent.xmin, 1);
                    const height = Math.max(extent.ymax - extent.ymin, 1);
                    const padded = {
                        xmin: extent.xmin - width * 0.18,
                        ymin: extent.ymin - height * 0.18,
                        xmax: extent.xmax + width * 0.18,
                        ymax: extent.ymax + height * 0.18,
                        spatialReference: { wkid: 102100 },
                    };
                    await view.goTo({ target: padded }, { duration: 0 });
                    return true;
                }""",
                extent,
            )
            if fitted:
                page.wait_for_timeout(1_000)
                self._close_map_popup(page)
                return
            LOGGER.info("ArcGIS view was not exposed; using parcel-size zoom fallback")
        except Exception:
            LOGGER.exception("Could not fit map to parcel extent")
        self._zoom_out_for_parcel_size(page)
        self._wait_for_map_to_settle(page, timeout_ms=6_000)
        self._close_map_popup(page)

    def _zoom_out_for_parcel_size(self, page: Page) -> None:
        extent = self._parcel_extent_102100()
        width = extent["xmax"] - extent["xmin"]
        height = extent["ymax"] - extent["ymin"]
        largest_dimension = max(width, height)
        zoom_delta = 1.0 if largest_dimension >= 10_000 else 0.5

        self.progress(f"Zooming out for parcel extent ({zoom_delta:g} level)")
        if self._set_arcgis_view_zoom(page, zoom_delta):
            return

        LOGGER.info("ArcGIS view zoom was not available; falling back to mouse wheel")
        size = page.viewport_size or {"width": 1600, "height": 900}
        map_center = page.evaluate(
            """() => {
                const isVisible = (element) => {
                    const style = window.getComputedStyle(element);
                    const box = element.getBoundingClientRect();
                    return box.width > 0 && box.height > 0 &&
                        style.display !== "none" &&
                        style.visibility !== "hidden";
                };
                const map = [...document.querySelectorAll(".esri-view, .map-component-container, .map-base, .multi-source-map")]
                    .find(isVisible);
                if (!map) {
                    return null;
                }
                const box = map.getBoundingClientRect();
                return {
                    x: box.x + box.width * 0.55,
                    y: box.y + box.height * 0.52,
                };
            }"""
        )
        x = float(map_center["x"]) if map_center else size["width"] * 0.55
        y = float(map_center["y"]) if map_center else size["height"] * 0.52
        page.mouse.move(x, y)
        if self.stop_event.is_set():
            raise RuntimeError("Run cancelled")
        page.mouse.wheel(0, 225)
        page.wait_for_timeout(650)

    def _set_arcgis_view_zoom(self, page: Page, zoom_delta: float) -> bool:
        try:
            return bool(
                page.evaluate(
                    """async (zoomDelta) => {
                        const candidates = [];
                        const manager = window._mapViewManager;
                        if (manager?.jimuMapViewGroups) {
                            for (const group of Object.values(manager.jimuMapViewGroups)) {
                                for (const jimuView of Object.values(group?.jimuMapViews || {})) {
                                    if (jimuView?.view) candidates.push(jimuView.view);
                                    if (jimuView?.mapComponent) candidates.push(jimuView.mapComponent);
                                }
                            }
                        }
                        const view = candidates.find((candidate) => {
                            try {
                                return candidate &&
                                    typeof candidate.goTo === "function" &&
                                    typeof candidate.zoom === "number" &&
                                    candidate.center;
                            } catch {
                                return false;
                            }
                        });
                        if (!view) {
                            return false;
                        }
                        const targetZoom = Math.max((view.constraints?.minZoom ?? 0), view.zoom - zoomDelta);
                        await view.goTo(
                            { center: view.center.clone ? view.center.clone() : view.center, zoom: targetZoom },
                            { duration: 0 }
                        );
                        return true;
                    }""",
                    zoom_delta,
                )
            )
        except Exception:
            LOGGER.exception("Could not set ArcGIS view zoom")
            return False

    def _parcel_extent_102100(self) -> dict[str, float]:
        geometry = self._get_parcel_geometry()
        points = [point for ring in geometry.get("rings", []) for point in ring]
        if not points:
            raise RuntimeError("Parcel geometry has no polygon rings.")
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        return {
            "xmin": min(xs),
            "ymin": min(ys),
            "xmax": max(xs),
            "ymax": max(ys),
        }

    def _prepare_aerial_base_for_environmental(self, page: Page) -> None:
        self.progress("Preparing aerial base map")
        self._close_map_popup(page)
        self._ensure_layer_manager_available(page)
        self._turn_on_aerial(page)
        self._close_map_popup(page)
        self._debug_screenshot(page, "05-aerial-base-ready")

    def _turn_on_aerial(self, page: Page) -> None:
        self.progress("Turning on aerial image")
        self._close_map_popup(page)
        self._wait_for_base_layers_or_aerial(page, timeout_ms=8_000)
        if self._enable_newest_aerial_imagery(page):
            return
        self._debug_screenshot(page, "05-aerial-layer-not-found")
        raise RuntimeError("Could not find the NCC Aerial Imagery visibility button.")

    def _wait_for_base_layers_or_aerial(self, page: Page, timeout_ms: int) -> bool:
        elapsed = 0
        step = 250
        while elapsed <= timeout_ms:
            if self.stop_event.is_set():
                raise RuntimeError("Run cancelled")
            try:
                ready = page.locator(
                    "calcite-list-item[title='Base Layers'], button[aria-label*='NCC Aerial Imagery'], calcite-list-item[title*='NCC Aerial Imagery']"
                ).evaluate_all(
                    """elements => elements.some((element) => {
                        const box = element.getBoundingClientRect();
                        return box.width > 0 && box.height > 0;
                    })"""
                )
                if ready:
                    return True
            except Exception:
                pass
            page.wait_for_timeout(step)
            elapsed += step
        return False

    def _prepare_environmental_map(self, page: Page, group_name: str) -> None:
        map_group = ENVIRONMENTAL_GROUPS.get(group_name)
        if not map_group:
            raise RuntimeError(f"Unknown environmental layer group: {group_name}")
        target_layers = map_group.layer_names

        self.progress(f"Preparing {group_name} map")
        self._close_map_popup(page)
        self._ensure_layer_manager_available(page)
        self._ensure_environmental_layers_visible(page)
        self._expand_environmental_sublayers(page)

        self._turn_off_visible_environmental_child_layers(page)
        self._turn_on_environmental_child_layers(page, target_layers)
        self._verify_environmental_group_state(page, group_name, target_layers)

        self._close_map_popup(page)
        self._debug_screenshot(page, f"06-environmental-ready-{safe_file_part(group_name)}")

    def _close_map_popup(self, page: Page) -> None:
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(100)
        except Exception:
            pass
        for selector in (
            ".esriPopup .titleButton.close",
            ".titleButton.close",
            ".esri-popup .esri-popup__button[title='Close']",
            ".esri-popup .esri-popup__button[aria-label='Close']",
            ".esri-popup calcite-action[title='Close']",
            ".esri-popup calcite-action[aria-label='Close']",
            ".esri-popup [title='Close']",
            ".esri-popup [aria-label='Close']",
            ".esri-popup__main-container .titleButton.close",
            ".esri-popup__main-container .titleButton.close",
            ".esri-popup__main-container .esri-popup__button[title='Close']",
            ".esri-popup__main-container .esri-popup__button--close",
            ".esri-popup__header-buttons .esri-popup__button",
            ".esri-popup__header-buttons button[title='Close']",
            ".esri-popup__header-buttons calcite-action[title='Close']",
            ".esri-popup__header-buttons calcite-action[aria-label='Close']",
            ".esri-popup__main-container button[aria-label='Close']",
            ".esri-popup__main-container [aria-label='Close']",
        ):
            try:
                controls = page.locator(selector)
                for index in range(min(controls.count(), 20)):
                    if controls.nth(index).is_visible(timeout=250):
                        controls.nth(index).click(timeout=750)
                        page.wait_for_timeout(150)
            except Exception:
                continue
        self._close_parcel_identifier_popup(page)
        self._close_visible_popup_by_dom(page)
        self._close_parcel_popup_by_geometry(page)
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(100)
        except Exception:
            pass

    def _close_parcel_identifier_popup(self, page: Page) -> None:
        try:
            closed = page.evaluate(
                """() => {
                    const isVisible = (element) => {
                        const style = window.getComputedStyle(element);
                        const box = element.getBoundingClientRect();
                        return box.width > 0 && box.height > 0 &&
                            style.display !== "none" &&
                            style.visibility !== "hidden" &&
                            Number(style.opacity || 1) > 0.05;
                    };

                    const panelContainsParcelId = (element) => {
                        let node = element;
                        for (let i = 0; node && i < 10; i += 1) {
                            if (node.innerText && /Parcel ID:/i.test(node.innerText)) {
                                return true;
                            }
                            node = node.parentElement;
                        }
                        return false;
                    };

                    const removeParcelOverlay = () => {
                        const viewportArea = window.innerWidth * window.innerHeight;
                        const candidates = [...document.querySelectorAll(
                            "calcite-flow, calcite-flow-item, .esri-popup, .esri-popup__main-container, " +
                            ".esri-popup__content, .esri-feature, .content-feature, [role='dialog'], [class*='popup'], [class*='feature']"
                        )];
                        for (const element of candidates) {
                            const text = element.innerText || element.textContent || "";
                            if (!/Parcel ID:/i.test(text) || !isVisible(element)) {
                                continue;
                            }
                            const box = element.getBoundingClientRect();
                            const area = box.width * box.height;
                            if (area > 0 && area < viewportArea * 0.65) {
                                element.remove();
                                return true;
                            }
                        }

                        const textNodes = [...document.querySelectorAll("div, section, article, calcite-panel, calcite-flow-item")];
                        for (const element of textNodes) {
                            const text = element.innerText || element.textContent || "";
                            if (!/Parcel ID:/i.test(text) || !isVisible(element)) {
                                continue;
                            }
                            let removable = element;
                            for (let i = 0; removable.parentElement && i < 8; i += 1) {
                                const parent = removable.parentElement;
                                const parentText = parent.innerText || parent.textContent || "";
                                const parentBox = parent.getBoundingClientRect();
                                const parentArea = parentBox.width * parentBox.height;
                                if (!/Parcel ID:/i.test(parentText) || parentArea >= viewportArea * 0.65) {
                                    break;
                                }
                                removable = parent;
                            }
                            const box = removable.getBoundingClientRect();
                            const area = box.width * box.height;
                            if (area > 0 && area < viewportArea * 0.65) {
                                removable.remove();
                                return true;
                            }
                        }
                        return false;
                    };

                    if (removeParcelOverlay()) {
                        return true;
                    }

                    const featureCards = [...document.querySelectorAll("calcite-flow-item.content-feature, calcite-flow-item[closable], calcite-flow-item")];
                    const parcelCard = featureCards.find((card) => {
                        const text = card.innerText || card.textContent || "";
                        return isVisible(card) && /Parcel ID:/i.test(text);
                    });
                    if (parcelCard) {
                        const shadowClose = parcelCard.shadowRoot
                            ? [...parcelCard.shadowRoot.querySelectorAll("button, calcite-action, [title], [aria-label]")]
                                .find((element) => {
                                    const label = [
                                        element.getAttribute("title"),
                                        element.getAttribute("aria-label"),
                                        element.textContent,
                                    ].filter(Boolean).join(" ").toLowerCase();
                                    return label.includes("close");
                                })
                            : null;
                        if (shadowClose) {
                            shadowClose.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, cancelable: true, composed: true, view: window }));
                            shadowClose.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, composed: true, view: window }));
                            shadowClose.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, composed: true, view: window }));
                            shadowClose.dispatchEvent(new MouseEvent("pointerup", { bubbles: true, cancelable: true, composed: true, view: window }));
                            shadowClose.click();
                        }
                        const flow = parcelCard.closest("calcite-flow");
                        if (flow) {
                            flow.remove();
                            return true;
                        }
                        parcelCard.removeAttribute("selected");
                        parcelCard.remove();
                        return true;
                    }

                    const parcelFlow = [...document.querySelectorAll("calcite-flow")].find((flow) => {
                        const text = flow.innerText || flow.textContent || "";
                        return isVisible(flow) && /Parcel ID:/i.test(text);
                    });
                    if (parcelFlow) {
                        parcelFlow.remove();
                        return true;
                    }

                    const buttons = [...document.querySelectorAll("button[aria-label='Close']")];
                    const closeButton = buttons.find((button) => {
                        const text = (button.innerText || button.textContent || "").trim();
                        return isVisible(button) &&
                            /close/i.test(text || button.getAttribute("aria-label") || "") &&
                            panelContainsParcelId(button);
                    });
                    if (!closeButton) {
                        return false;
                    }
                    closeButton.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, cancelable: true, view: window }));
                    closeButton.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, view: window }));
                    closeButton.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, view: window }));
                    closeButton.dispatchEvent(new MouseEvent("pointerup", { bubbles: true, cancelable: true, view: window }));
                    closeButton.click();
                    removeParcelOverlay();
                    return true;
                }"""
            )
            if closed:
                page.wait_for_timeout(300)
        except Exception:
            LOGGER.exception("Could not close Parcel Identifier popup")

    def _remove_visible_parcel_identifier_cards(self, page: Page) -> bool:
        try:
            return bool(
                page.evaluate(
                    """() => {
                        const viewportArea = window.innerWidth * window.innerHeight;
                        const allElementsDeep = (root = document) => {
                            const elements = [];
                            const visit = (node) => {
                                if (!node) return;
                                if (node.nodeType === Node.ELEMENT_NODE) {
                                    elements.push(node);
                                    if (node.shadowRoot) visit(node.shadowRoot);
                                }
                                for (const child of node.children || []) visit(child);
                            };
                            visit(root);
                            return elements;
                        };
                        const isVisible = (element) => {
                            const style = window.getComputedStyle(element);
                            const box = element.getBoundingClientRect();
                            return box.width > 0 && box.height > 0 &&
                                style.display !== "none" &&
                                style.visibility !== "hidden" &&
                                Number(style.opacity || 1) > 0.05;
                        };
                        const removableFor = (element) => {
                            let node = element;
                            while (node && node.nodeType !== Node.ELEMENT_NODE) node = node.parentNode;
                            if (node?.getRootNode?.() instanceof ShadowRoot) {
                                node = node.getRootNode().host;
                            }
                            const hostContainer = node?.closest?.("calcite-flow, calcite-flow-item, .esri-popup, .esri-popup__main-container, .content-feature, [class*='popup'], [class*='feature']");
                            if (hostContainer) {
                                return hostContainer;
                            }
                            let removable = node;
                            for (let i = 0; removable && removable.parentElement && i < 10; i += 1) {
                                const parent = removable.parentElement;
                                const parentText = parent.innerText || parent.textContent || "";
                                const parentBox = parent.getBoundingClientRect();
                                const parentArea = parentBox.width * parentBox.height;
                                if (!/Parcel ID:/i.test(parentText) || parentArea >= viewportArea * 0.65) {
                                    break;
                                }
                                removable = parent;
                            }
                            return removable;
                        };
                        for (const element of allElementsDeep()) {
                            const text = element.innerText || element.textContent || "";
                            if (!/Parcel ID:/i.test(text) || !isVisible(element)) {
                                continue;
                            }
                            const removable = removableFor(element);
                            if (removable && removable !== document.body && removable !== document.documentElement) {
                                removable.remove();
                                for (const shell of allElementsDeep()) {
                                    const box = shell.getBoundingClientRect?.();
                                    if (!box || !isVisible(shell)) continue;
                                    const area = box.width * box.height;
                                    const label = [
                                        shell.tagName,
                                        shell.className,
                                        shell.getAttribute?.("role"),
                                        shell.getAttribute?.("aria-label"),
                                        shell.getAttribute?.("title"),
                                    ].filter(Boolean).join(" ");
                                    if (area > 0 && area < viewportArea * 0.65 &&
                                        box.x > 350 && box.y > 60 &&
                                        /calcite-flow|flow-item|popup|feature|dialog|content-feature/i.test(label)) {
                                        shell.remove();
                                        break;
                                    }
                                }
                                return true;
                            }
                        }
                        return false;
                    }"""
                )
            )
        except Exception:
            LOGGER.exception("Could not remove visible Parcel Identifier card")
            return False

    def _parcel_identifier_card_visible(self, page: Page) -> bool:
        try:
            return bool(
                page.evaluate(
                    """() => {
                        const allElementsDeep = (root = document) => {
                            const elements = [];
                            const visit = (node) => {
                                if (!node) return;
                                if (node.nodeType === Node.ELEMENT_NODE) {
                                    elements.push(node);
                                    if (node.shadowRoot) visit(node.shadowRoot);
                                }
                                for (const child of node.children || []) visit(child);
                            };
                            visit(root);
                            return elements;
                        };
                        const isVisible = (element) => {
                            const style = window.getComputedStyle(element);
                            const box = element.getBoundingClientRect();
                            return box.width > 0 && box.height > 0 &&
                                style.display !== "none" &&
                                style.visibility !== "hidden" &&
                                Number(style.opacity || 1) > 0.05;
                        };
                        const viewportArea = window.innerWidth * window.innerHeight;
                        return allElementsDeep().some((element) => {
                            const text = element.innerText || element.textContent || "";
                            if (!/Parcel ID:/i.test(text) || !isVisible(element)) {
                                return false;
                            }
                            const box = element.getBoundingClientRect();
                            const area = box.width * box.height;
                            return area > 0 && area < viewportArea * 0.65;
                        });
                    }"""
                )
            )
        except Exception:
            LOGGER.exception("Could not check Parcel Identifier visibility")
            return False

    def _ensure_parcel_identifier_closed_before_capture(self, page: Page) -> None:
        for attempt in range(4):
            self._close_map_popup(page)
            self._remove_visible_parcel_identifier_cards(page)
            page.wait_for_timeout(250)
            if not self._parcel_identifier_card_visible(page):
                return
            LOGGER.info("Parcel Identifier card still visible before capture; retrying close (%s)", attempt + 1)
        self._debug_screenshot(page, "06-parcel-identifier-still-visible")
        raise RuntimeError("Parcel Identifier card is still visible; screenshot was not taken.")

    def _close_visible_popup_by_dom(self, page: Page) -> None:
        try:
            closed = page.evaluate(
                """() => {
                    const isVisible = (element) => {
                        const style = window.getComputedStyle(element);
                        const box = element.getBoundingClientRect();
                        return box.width > 0 && box.height > 0 &&
                            style.display !== "none" &&
                            style.visibility !== "hidden" &&
                            Number(style.opacity || 1) > 0.05;
                    };
                    const popupSelectors = [
                        ".esri-popup",
                        ".esri-popup__main-container",
                        ".esriPopup",
                        "[class*='popup']"
                    ];
                    for (const popup of document.querySelectorAll(popupSelectors.join(","))) {
                        if (!isVisible(popup)) {
                            continue;
                        }
                        const close = [...popup.querySelectorAll("button, [role='button'], [title], [aria-label], .titleButton.close, calcite-action")]
                            .find((element) => {
                                if (!isVisible(element)) {
                                    return false;
                                }
                                const label = [
                                    element.getAttribute("title"),
                                    element.getAttribute("aria-label"),
                                    element.textContent,
                                    element.className,
                                ].filter(Boolean).join(" ").toLowerCase();
                                return label.includes("close") || label.includes("titlebutton close");
                            });
                        if (close) {
                            close.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, view: window }));
                            close.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, view: window }));
                            close.click();
                            return true;
                        }
                    }
                    return false;
                }"""
            )
            if closed:
                page.wait_for_timeout(200)
        except Exception:
            LOGGER.exception("Could not close popup by DOM")

    def _expand_environmental_sublayers(self, page: Page) -> None:
        if self._environmental_sublayers_are_visible(page):
            return
        self.progress("Opening Environmental sublayers")
        expand_control = page.locator('[role="row"][aria-label="Environmental"] .expanded-container[title="Expand"]').first
        try:
            if expand_control.count():
                expand_control.click(timeout=5_000)
            else:
                raise RuntimeError("Environmental expand control not found")
        except Exception:
            LOGGER.exception("Could not click Environmental expand control")
            self._debug_screenshot(page, "06-environmental-expand-not-found")
            raise RuntimeError("Could not find the Environmental sublayer expand control.")
        page.wait_for_timeout(600)
        if not self._environmental_sublayers_are_visible(page):
            self._debug_screenshot(page, "06-environmental-sublayers-not-visible")
            LOGGER.info("Environmental sublayer visibility check did not pass; continuing after expand click")

    def _environmental_sublayers_are_visible(self, page: Page) -> bool:
        try:
            for layer_name in ("Buoys", "NHD Lines", "NHD Waterbodies", "Swamp/Marsh", "State Wetlands", "Forests", "FEMA Layers"):
                if self._visible_layer_label_exists(page, f"Show {layer_name}") or self._visible_layer_label_exists(page, f"Hide {layer_name}"):
                    return True
            for text in ("Buoys", "Watersheds", "Topography", "FEMA Layers", "NHD Lines", "NHD Waterbodies", "Swamp/Marsh", "State Wetlands"):
                loc = page.get_by_text(text, exact=True).first
                if loc.count() and loc.is_visible(timeout=250):
                    return True
            return bool(
                page.evaluate(
                    """() => {
                        const row = [...document.querySelectorAll('[role="row"][aria-label="Environmental"]')]
                            .find((element) => {
                                const box = element.getBoundingClientRect();
                                return box.width > 0 && box.height > 0;
                            });
                        if (!row) return false;
                        return row.getAttribute("aria-expanded") === "true" ||
                            [...document.querySelectorAll('calcite-list-item[title], button[aria-label], calcite-action[title]')]
                                .some((element) => {
                                    const box = element.getBoundingClientRect();
                                    const label = element.getAttribute("title") || element.getAttribute("aria-label") || "";
                                    return box.width > 0 && box.height > 0 &&
                                        /Buoys|Watersheds|Topography|NHD Lines|NHD Waterbodies|Swamp\\/Marsh|State Wetlands|Coastal Zone|FEMA|Floodplain/i.test(label);
                                });
                    }"""
                )
            )
        except Exception:
            LOGGER.exception("Could not inspect Environmental sublayer visibility")
            return False

    def _turn_off_visible_environmental_child_layers(self, page: Page) -> None:
        self.progress("Clearing Environmental sublayers")
        clicked_count = self._click_visible_layer_controls(
            page,
            [f"Hide {name}" for name in self._environmental_child_names()],
        )
        LOGGER.info("Cleared %s visible Environmental child layers", clicked_count)
        page.wait_for_timeout(500)

    def _turn_on_environmental_child_layers(self, page: Page, target_layers: tuple[str, ...]) -> None:
        labels = self._visible_group_parent_labels(target_layers) + target_layers
        for label in labels:
            self.progress(f"Turning on {label}")
            if self._visible_layer_label_exists(page, f"Hide {label}"):
                continue
            if not self._click_visible_layer_controls(page, (f"Show {label}",)):
                LOGGER.info("Environmental child layer button not found: Show %s", label)
            page.wait_for_timeout(350)

    def _verify_environmental_group_state(self, page: Page, group_name: str, target_layers: tuple[str, ...]) -> None:
        self.progress(f"Confirming {group_name} layer state")
        problems: list[str] = []
        group_parents = set(self._visible_group_parent_labels(target_layers))
        allowed_on = {"Environmental", *group_parents, *target_layers}
        for layer_name in self._environmental_child_names():
            if layer_name in allowed_on:
                continue
            if self._visible_layer_label_exists(page, f"Hide {layer_name}"):
                problems.append(f"{layer_name} is still visible")

        if problems:
            self._debug_screenshot(page, f"06-{safe_file_part(group_name)}-state-not-confirmed")
            raise RuntimeError("; ".join(problems))

    def _visible_group_parent_labels(self, target_layers: tuple[str, ...]) -> tuple[str, ...]:
        if any(layer.startswith("FEMA ") for layer in target_layers):
            return ("FEMA Layers",)
        return ()

    def _environmental_child_names(self) -> tuple[str, ...]:
        return (
            "Buoys",
            "Watersheds",
            "Topography",
            "Swamp/Marsh",
            "State Wetlands",
            "Coastal Zone",
            "Erosion Prone Soils",
            "FEMA Layers",
            "FEMA 100-year Floodplain (1 PCT Annual Chance)",
            "FEMA 500-year Floodplain (0.2 PCT Annual Chance)",
            "WRPA Floodplains",
            "National Wetlands",
            "Forests",
            "Critical Natural Areas",
            "NHD Lines",
            "NHD Waterbodies",
            "Coastal Flooding Evacuation Zones",
        )

    def _visible_layer_label_exists(self, page: Page, label: str) -> bool:
        locator = self._visible_layer_control(page, label)
        return locator is not None

    def _click_visible_layer_controls(self, page: Page, labels: tuple[str, ...] | list[str]) -> int:
        clicked = 0
        for label in labels:
            control = self._visible_layer_control(page, label)
            if control is None:
                continue
            try:
                control.click(timeout=2_000)
                clicked += 1
                page.wait_for_timeout(250)
            except Exception:
                LOGGER.exception("Could not click visible layer control %s", label)
        return clicked

    def _visible_layer_control(self, page: Page, label: str):
        selectors = (
            f'button[aria-label="{label}"]',
            f'calcite-action[title="{label}"]',
        )
        for selector in selectors:
            try:
                controls = page.locator(selector)
                for index in range(controls.count()):
                    control = controls.nth(index)
                    if control.is_visible(timeout=250):
                        return control
            except Exception:
                continue
        return None

    def _ensure_layer_manager_available(self, page: Page) -> None:
        if self._wait_for_layer_manager(page, timeout_ms=8_000):
            LOGGER.info("Layer manager is already visible")
            return
        self._open_layer_panel(page)
        if not self._wait_for_layer_manager(page, timeout_ms=8_000):
            self._debug_screenshot(page, "06-layer-manager-not-visible")
            raise RuntimeError("Could not open the layer manager.")

    def _reopen_layer_manager_after_capture(self, page: Page) -> None:
        self.progress("Reopening layer manager")
        self._ensure_layer_manager_available(page)
        self._close_map_popup(page)
        self._expand_environmental_sublayers(page)

    def _open_layer_panel(self, page: Page) -> bool:
        if self._click_left_sidebar_expand(page):
            return True

        selectors = (
            "button.sidebar-controller[title='Expand']",
            "button.sidebar-controller[aria-label='Expand']",
            "button[title='Expand'][aria-label='Expand']",
        )
        for selector in selectors:
            try:
                controls = page.locator(selector)
                for index in range(controls.count()):
                    control = controls.nth(index)
                    if not control.is_visible(timeout=250):
                        continue
                    LOGGER.info("Opening layer manager with selector=%s index=%s", selector, index)
                    control.click(timeout=2_000)
                    if self._wait_for_layer_manager(page, timeout_ms=5_000):
                        return True
            except Exception:
                LOGGER.exception("Could not click layer manager expand control")
        return False

    def _click_left_sidebar_expand(self, page: Page) -> bool:
        try:
            clicked = page.evaluate(
                """() => {
                    const isVisible = (element) => {
                        const style = window.getComputedStyle(element);
                        const box = element.getBoundingClientRect();
                        return box.width > 0 && box.height > 0 &&
                            style.display !== "none" &&
                            style.visibility !== "hidden" &&
                            Number(style.opacity || 1) > 0.05;
                    };
                    const button = [...document.querySelectorAll("button.sidebar-controller, button[title='Expand'], button[aria-label='Expand']")]
                        .find((element) => {
                            const box = element.getBoundingClientRect();
                            const label = [
                                element.getAttribute("title"),
                                element.getAttribute("aria-label"),
                                element.textContent,
                                element.className,
                            ].filter(Boolean).join(" ").toLowerCase();
                            return isVisible(element) &&
                                box.x <= 25 &&
                                box.width <= 40 &&
                                box.height >= 30 &&
                                label.includes("expand");
                        });
                    if (!button) {
                        return false;
                    }
                    button.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, view: window }));
                    button.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, view: window }));
                    button.click();
                    return true;
                }"""
            )
            if clicked and self._wait_for_layer_manager(page, timeout_ms=5_000):
                return True
        except Exception:
            LOGGER.exception("Could not expand left sidebar by DOM click")
        return False

    def _layer_toolbar_targets(self, page: Page, size: dict[str, int]) -> tuple[tuple[float, float], ...]:
        try:
            targets = page.evaluate(
                """() => {
                    const isVisible = (element) => {
                        const style = window.getComputedStyle(element);
                        const box = element.getBoundingClientRect();
                        return box.width > 0 && box.height > 0 &&
                            style.display !== "none" && style.visibility !== "hidden";
                    };
                    return [...document.querySelectorAll("button, [role='button'], [title], [aria-label], img")]
                        .map((element) => {
                            const box = element.getBoundingClientRect();
                            const label = [
                                element.getAttribute("title"),
                                element.getAttribute("aria-label"),
                                element.getAttribute("alt"),
                                element.textContent,
                                element.getAttribute("src"),
                                element.className,
                            ].filter(Boolean).join(" ").toLowerCase();
                            return { label, x: box.x + box.width / 2, y: box.y + box.height / 2, width: box.width, height: box.height };
                        })
                        .filter((item) => item.width > 0 && item.height > 0 &&
                            item.y < 60 && item.x > window.innerWidth * 0.75 &&
                            /layer|list|toc/.test(item.label))
                        .map((item) => [item.x, item.y]);
                }"""
            )
            if targets:
                return tuple((float(x), float(y)) for x, y in targets)
        except Exception:
            LOGGER.exception("Could not inspect layer toolbar targets")
        return (
            (size["width"] - 22, 22),
            (size["width"] - 54, 22),
            (size["width"] - 86, 22),
        )

    def _close_right_side_panel(self, page: Page) -> None:
        try:
            size = page.viewport_size or {"width": 1600, "height": 900}
            close_buttons = page.locator("[title='Close'], [aria-label='Close']")
            for index in range(close_buttons.count()):
                button = close_buttons.nth(index)
                if not button.is_visible(timeout=250):
                    continue
                box = button.bounding_box(timeout=500)
                if box and box["x"] > size["width"] * 0.6 and box["y"] < 90:
                    button.click(timeout=1_000)
                    page.wait_for_timeout(300)
                    return
        except Exception:
            LOGGER.exception("Could not close right side panel")

    def _wait_for_layer_manager(self, page: Page, timeout_ms: int) -> bool:
        elapsed = 0
        step = 250
        while elapsed <= timeout_ms:
            if self.stop_event.is_set():
                raise RuntimeError("Run cancelled")
            if self._layer_manager_is_visible(page):
                return True
            page.wait_for_timeout(step)
            elapsed += step
        return False

    def _layer_manager_is_visible(self, page: Page) -> bool:
        try:
            return bool(
                page.locator("calcite-list-item[title='Environmental'], button[aria-label='Show Environmental'], button[aria-label='Hide Environmental'], button[aria-label*='NCC Aerial Imagery']").evaluate_all(
                    """elements => elements.some((element) => {
                        const box = element.getBoundingClientRect();
                        return box.width > 0 && box.height > 0;
                    })"""
                )
            )
        except Exception:
            LOGGER.exception("Could not inspect layer manager visibility")
            return False

    def _ensure_environmental_layers_visible(self, page: Page) -> None:
        if self._environmental_parent_enabled:
            return
        self.progress("Turning on Environmental")
        if self._label_exists(page, "Hide Environmental"):
            self._environmental_parent_enabled = True
            return
        if self._click_layer_button(page, "Show Environmental"):
            page.wait_for_timeout(600)
            self._environmental_parent_enabled = True
            return

        self._debug_screenshot(page, "06-environmental-button-not-found")
        raise RuntimeError("Could not find the Show Environmental visibility button.")

    def _any_environmental_child_visible(self, page: Page) -> bool:
        try:
            labels = page.locator("button[aria-label]").evaluate_all(
                """buttons => buttons.map(button => button.getAttribute("aria-label") || "")"""
            )
        except Exception:
            LOGGER.exception("Could not inspect visible layer labels")
            return False
        return any(
            label.endswith(layer_name)
            for label in labels
            for layer_name in ENVIRONMENTAL_LAYERS
        )

    def _capture_current_map_pdf(self, page: Page, label: str, debug_name: str) -> tuple[Path, Path, Path | None]:
        image_path = self._output_path(label, ".png")
        pdf_path = self._output_path(label, ".pdf")
        self.progress(f"Saving {label.lower()}")
        self._close_map_popup(page)
        self._collapse_panels(page)
        self._wait_for_map_to_settle(page)
        self._close_map_popup(page)
        page.wait_for_timeout(200)
        self._ensure_parcel_identifier_closed_before_capture(page)
        page.screenshot(path=str(image_path), full_page=False)
        legend_path = FEMA_LEGEND_PATH if label.startswith("FEMA Floodplain") else None
        image_to_full_bleed_pdf(image_path, pdf_path, overlay_image_path=legend_path)
        self._debug_screenshot(page, debug_name)
        return pdf_path, image_path, legend_path

    def _create_combined_environmental_pdf(self, image_pages: list[tuple[Path, Path | None]]) -> Path:
        combined_pdf_path = self._output_path("Environmental Map", ".pdf")
        self.progress("Saving combined environmental map")
        images_to_full_bleed_pdf(image_pages, combined_pdf_path)
        return combined_pdf_path

    def _wait_for_map_to_settle(self, page: Page, timeout_ms: int = 20_000) -> None:
        self.progress("Waiting for map to finish loading")
        elapsed = 0
        step = 300
        quiet_checks = 0
        required_quiet_checks = 5

        while elapsed <= timeout_ms:
            if self.stop_event.is_set():
                raise RuntimeError("Run cancelled")

            try:
                active_count = page.evaluate(
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

                        const loadingSelectors = [
                            "calcite-loader",
                            ".esri-loader",
                            ".esri-spinner",
                            ".esri-view__loading-indicator",
                            ".esri-layer-list__updating-indicator",
                            "[aria-busy='true']",
                            "[class*='loading']",
                            "[class*='loader']",
                            "[class*='spinner']"
                        ];
                        const loadingElements = loadingSelectors
                            .flatMap((selector) => [...document.querySelectorAll(selector)])
                            .filter(isVisible);
                        const pendingImages = [...document.images].filter((image) => !image.complete).length;
                        return loadingElements.length + pendingImages;
                    }"""
                )
            except Exception:
                LOGGER.exception("Could not inspect map loading state")
                active_count = 0

            if active_count == 0:
                quiet_checks += 1
                if quiet_checks >= required_quiet_checks:
                    page.wait_for_timeout(700)
                    return
            else:
                quiet_checks = 0

            page.wait_for_timeout(step)
            elapsed += step

        LOGGER.info("Map settle wait timed out after %sms; continuing with screenshot", timeout_ms)

    def _set_layer_enabled(self, page: Page, layer_name: str, enabled: bool) -> None:
        if self.stop_event.is_set():
            raise RuntimeError("Run cancelled")

        state = "on" if enabled else "off"
        self.progress(f"Turning {state} {layer_name}")
        if self._layer_has_state(page, layer_name, enabled):
            return

        click_label = f"{'Show' if enabled else 'Hide'} {layer_name}"
        if self._click_layer_button(page, click_label):
            page.wait_for_timeout(350)
            return

        LOGGER.info("Layer button not found for %s", click_label)

    def _layer_has_state(self, page: Page, layer_name: str, enabled: bool) -> bool:
        desired_label = f"{'Hide' if enabled else 'Show'} {layer_name}"
        return self._label_exists(page, desired_label)

    def _label_exists(self, page: Page, label: str) -> bool:
        try:
            return bool(
                page.locator("button[aria-label]").evaluate_all(
                    "(buttons, label) => buttons.some(button => button.getAttribute('aria-label') === label)",
                    label,
                )
            )
        except Exception:
            LOGGER.exception("Could not inspect layer button labels")
            return False

    def _click_layer_button(self, page: Page, label: str) -> bool:
        try:
            button = page.get_by_role("button", name=label, exact=True).first
            if button.count():
                actual_label = button.get_attribute("aria-label")
                if actual_label != label:
                    LOGGER.info("Refusing mismatched role click target expected=%s actual=%s", label, actual_label)
                    return False
                LOGGER.info("Clicking exact role button label=%s", label)
                button.scroll_into_view_if_needed(timeout=5_000)
                button.click(timeout=5_000)
                return True

            handle = page.evaluate_handle(
                """(label) => {
                    const buttons = [...document.querySelectorAll("button[aria-label]")];
                    return buttons.find((button) => button.getAttribute("aria-label") === label) || null;
                }""",
                label,
            )
            element = handle.as_element()
            if element is None:
                return False

            actual_label = element.get_attribute("aria-label")
            if actual_label != label:
                LOGGER.info("Refusing mismatched layer click target expected=%s actual=%s", label, actual_label)
                return False

            LOGGER.info("Clicking exact layer button label=%s", label)
            element.scroll_into_view_if_needed(timeout=5_000)
            element.click(timeout=5_000)
            return True
        except Exception:
            LOGGER.exception("Could not click layer button %s", label)
            return False
