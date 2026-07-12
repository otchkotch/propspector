from __future__ import annotations

import json
import logging
import math
import tempfile
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

from .municipal_bots import normalize_municipal_zoning_code
from .environmental_config import (
    ALL_RESOURCES_GROUP,
    ENVIRONMENTAL_GROUPS,
    ENVIRONMENTAL_LAYER_IDS,
    ENVIRONMENTAL_LAYER_SOURCES,
    ENVIRONMENTAL_MAPSERVER_URL,
    FEMA_LEGEND_PATH,
    IMAGERY_2025_MAPSERVER_URL,
    PARCEL_LAYER_QUERY_URL,
    PARCEL_MAPSERVER_URL,
    RESOURCE_STATUS_ORDER,
    ResourcePresence,
)
from .parcel_lookup import address_where, fallback_address_where, parcel_key, parcel_where, split_parcel_inputs
from .pdf_tools import image_to_full_bleed_pdf, images_to_full_bleed_pdf, safe_file_part


LOGGER = logging.getLogger("parcel_packet.environmental_widget_runner")
Progress = Callable[[str], None]
ResourcePresenceCallback = Callable[[tuple[ResourcePresence, ...]], None]

EXPORT_WIDTH = 3300
EXPORT_HEIGHT = 2550
EXPORT_DPI = 300
PREVIEW_WIDTH = 1320
PREVIEW_HEIGHT = 1020
PREVIEW_DPI = 120
MAP_SPATIAL_REFERENCE = "102657"
GEOMETRY_INTERSECT_URL = "https://gis.nccde.org/agsserver/rest/services/Utilities/Geometry/GeometryServer/intersect"
GEOMETRY_AREAS_URL = "https://gis.nccde.org/agsserver/rest/services/Utilities/Geometry/GeometryServer/areasAndLengths"
ACRE_SF = 43560.0
PARCEL_CONTEXT_RATIO = 0.22
MIN_CONTEXT_FEET = 250.0
PREVIEW_CONTEXT_RATIO = 0.40
PREVIEW_MIN_CONTEXT_FEET = 450.0
TOUCHING_ROAD_SEARCH_FEET = 140.0
ROADS_LAYER_QUERY_URL = "https://gis.nccde.org/agsserver/rest/services/BaseMaps/Base_Layers/MapServer/8/query"
ZONING_LAYER_QUERY_URL = "https://gis.nccde.org/agsserver/rest/services/BaseMaps/Zoning/MapServer/6/query"
MUNICIPAL_ZONING_LAYER_QUERY_URL = "https://gis.nccde.org/agsserver/rest/services/BaseMaps/NCC_Zoning/MapServer/4/query"
NCC_ZONING_MAPSERVER_URL = "https://gis.nccde.org/agsserver/rest/services/BaseMaps/NCC_Zoning/MapServer"
COUNTY_ZONING_FALLBACK_LAYER_IDS = (
    8,
    9,
    10,
    11,
    12,
    13,
    14,
    15,
    16,
    17,
    18,
    19,
    20,
    21,
    22,
    23,
    24,
    26,
    27,
    28,
    29,
    30,
    31,
    32,
    33,
    34,
)
ROOT = Path(__file__).resolve().parents[1]
NUNITO_FONT_PATH = ROOT / "assets" / "fonts" / "NunitoSans.ttf"
ARIAL_BLACK_FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/ariblk.ttf"),
    Path("C:/Windows/Fonts/Arial Black.ttf"),
)


@dataclass(frozen=True)
class DirectMapResult:
    environmental_pdf_paths: tuple[Path, ...]
    resource_statuses: tuple[ResourcePresence, ...]
    combined_pdf_path: Path | None = None


@dataclass(frozen=True)
class PreviewResult:
    resource_statuses: tuple[ResourcePresence, ...]
    preview: PreviewBundle


@dataclass(frozen=True)
class ParcelGeometry:
    parcel_number: str
    geometry: dict
    extent: tuple[float, float, float, float]
    attributes: dict


@dataclass(frozen=True)
class PreviewBundle:
    base_image: Image.Image
    layer_images: dict[str, Image.Image]
    road_overlay_image: Image.Image
    parcel_outline_image: Image.Image
    default_visible_layers: tuple[str, ...]
    parcel_facts: dict[str, str]
    zoning_districts: tuple[str, ...]


@dataclass(frozen=True)
class RoadFeature:
    label: str
    road_class: int
    paths: tuple[tuple[tuple[float, float], ...], ...]


PreviewCallback = Callable[[PreviewBundle], None]


class EnvironmentalWidgetRunner:
    def __init__(
        self,
        parcel_number: str,
        destination: Path,
        progress: Progress,
        stop_event: threading.Event,
        environmental_group: str = ALL_RESOURCES_GROUP,
        resource_status_callback: ResourcePresenceCallback | None = None,
        preview_callback: PreviewCallback | None = None,
    ) -> None:
        self.parcel_number = parcel_number.strip()
        self.parcel_numbers = split_parcel_inputs(self.parcel_number)
        self.search_parcel_number = parcel_key(self.parcel_numbers[0] if self.parcel_numbers else self.parcel_number)
        self.destination = destination
        self.progress = progress
        self.stop_event = stop_event
        self.environmental_group = environmental_group
        self.resource_status_callback = resource_status_callback
        self.preview_callback = preview_callback

    def run(self) -> DirectMapResult:
        preview_result = self.prepare_preview()
        pdf_paths = self.build_pdf_package()
        combined_pdf = pdf_paths[-1] if pdf_paths else None
        return DirectMapResult(
            environmental_pdf_paths=tuple(pdf_paths),
            resource_statuses=preview_result.resource_statuses,
            combined_pdf_path=combined_pdf,
        )

    def prepare_preview(self) -> PreviewResult:
        self.destination.mkdir(parents=True, exist_ok=True)
        selected_groups = self._selected_group_names()

        parcel = self._fetch_parcel_geometry()
        self._check_cancelled()
        if self.preview_callback:
            self.progress("Building aerial preview")
            self.preview_callback(self._render_preview_bundle(parcel, (), selected_groups, include_layers=False))
        self._check_cancelled()
        statuses = self._check_resource_presence(parcel.geometry)
        if self.resource_status_callback:
            self.resource_status_callback(statuses)
        preview = self._render_preview_bundle(parcel, statuses, selected_groups, include_layers=True)
        if self.preview_callback:
            self.preview_callback(preview)
        return PreviewResult(resource_statuses=statuses, preview=preview)

    def build_pdf_package(self) -> tuple[Path, ...]:
        self.destination.mkdir(parents=True, exist_ok=True)
        selected_groups = self._selected_group_names()
        parcel = self._fetch_parcel_geometry()
        with tempfile.TemporaryDirectory(prefix="environmental_widget_") as temp_name:
            temp_dir = Path(temp_name)
            image_pages = self._render_group_images(parcel, selected_groups, temp_dir)
            pdf_paths = self._write_pdfs(image_pages)
        return tuple(pdf_paths)

    def _selected_group_names(self) -> tuple[str, ...]:
        if self.environmental_group == ALL_RESOURCES_GROUP:
            return tuple(ENVIRONMENTAL_GROUPS.keys())
        if self.environmental_group not in ENVIRONMENTAL_GROUPS:
            raise RuntimeError(f"Unknown environmental map group: {self.environmental_group}")
        return (self.environmental_group,)

    def _fetch_parcel_geometry(self) -> ParcelGeometry:
        self.progress("Finding parcel geometry")
        if self.parcel_numbers:
            feature = self._query_parcel_feature(parcel_where(self.search_parcel_number), self.search_parcel_number)
        else:
            feature = None
            for where in (address_where(self.parcel_number), fallback_address_where(self.parcel_number)):
                if where:
                    feature = self._query_parcel_feature(where, self.parcel_number, required=False)
                    if feature:
                        break
            if not feature:
                raise RuntimeError("Parcel geometry was not found in the county GIS service.")

        geometry = feature.get("geometry") or {}
        extent = self._geometry_extent(geometry)
        attributes = feature.get("attributes") or {}
        parcel_number = (
            attributes.get("PARCELNO")
            or attributes.get("PRCLID")
            or attributes.get("SHORTPRCL")
            or self.search_parcel_number
        )
        return ParcelGeometry(parcel_number=str(parcel_number), geometry=geometry, extent=extent, attributes=attributes)

    def _query_parcel_feature(self, where: str, fallback_label: str, required: bool = True) -> dict | None:
        data = self._fetch_json(
            PARCEL_LAYER_QUERY_URL,
            {
                "f": "json",
                "where": where,
                "outFields": "PARCELNO,PRCLID,SHORTPRCL,ADDRESS,PROPCITY,PROPSTATE,PROPZIP,CNTCTLAST,PRIMADDR",
                "returnGeometry": "true",
                "outSR": MAP_SPATIAL_REFERENCE,
            },
        )
        features = data.get("features") or []
        if features:
            return sorted(features, key=lambda feature: 0 if (feature.get("attributes") or {}).get("PRIMADDR") == "Y" else 1)[0]
        if required:
            raise RuntimeError(f"Parcel geometry was not found for {fallback_label}.")
        return None

    def _check_resource_presence(self, parcel_geometry: dict) -> tuple[ResourcePresence, ...]:
        self.progress("Checking environmental resources")

        def check(name: str) -> ResourcePresence:
            self._check_cancelled()
            layer = ENVIRONMENTAL_LAYER_SOURCES.get(name)
            if layer is None:
                return ResourcePresence(name=name, status="Unknown", error="No layer mapped")
            try:
                count, raw_acres = self._query_intersection_stats(layer.mapserver_url, layer.layer_id, parcel_geometry)
            except Exception as exc:
                LOGGER.exception("Could not check environmental resource %s", name)
                return ResourcePresence(name=name, status="Unknown", error=str(exc))
            return ResourcePresence(name=name, status="Present" if count > 0 else "Absent", count=count, raw_acres=raw_acres)

        statuses: dict[str, ResourcePresence] = {}
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(check, name): name for name in RESOURCE_STATUS_ORDER}
            for future in as_completed(futures):
                statuses[futures[future]] = future.result()
        return tuple(statuses[name] for name in RESOURCE_STATUS_ORDER)

    def _query_intersection_count(self, layer_id: int, parcel_geometry: dict) -> int:
        count, _raw_acres = self._query_intersection_stats(ENVIRONMENTAL_MAPSERVER_URL, layer_id, parcel_geometry)
        return count

    def _query_intersection_stats(self, mapserver_url: str, layer_id: int, parcel_geometry: dict) -> tuple[int, float | None]:
        data = self._fetch_json(
            f"{mapserver_url}/{layer_id}/query",
            {
                "f": "json",
                "where": "1=1",
                "outFields": "OBJECTID",
                "returnGeometry": "true",
                "outSR": MAP_SPATIAL_REFERENCE,
                "geometry": json.dumps(parcel_geometry, separators=(",", ":")),
                "geometryType": "esriGeometryPolygon",
                "inSR": MAP_SPATIAL_REFERENCE,
                "spatialRel": "esriSpatialRelIntersects",
            },
        )
        features = data.get("features") or []
        polygon_geometries = []
        for feature in features:
            geometry = feature.get("geometry") or {}
            if geometry.get("rings"):
                geometry["spatialReference"] = {"wkid": int(MAP_SPATIAL_REFERENCE)}
                polygon_geometries.append(geometry)
        if not polygon_geometries:
            return len(features), None

        parcel = dict(parcel_geometry)
        parcel["spatialReference"] = {"wkid": int(MAP_SPATIAL_REFERENCE)}
        clipped = self._fetch_json(
            GEOMETRY_INTERSECT_URL,
            {
                "f": "json",
                "sr": MAP_SPATIAL_REFERENCE,
                "geometry": json.dumps({"geometryType": "esriGeometryPolygon", "geometry": parcel}, separators=(",", ":")),
                "geometries": json.dumps({"geometryType": "esriGeometryPolygon", "geometries": polygon_geometries}, separators=(",", ":")),
            },
        )
        clipped_geometries = [geometry for geometry in (clipped.get("geometries") or []) if geometry.get("rings")]
        raw_acres = self._geometry_area_acres(clipped_geometries)
        parcel_acres = self._geometry_area_acres([parcel])
        if parcel_acres > 0 and raw_acres > parcel_acres:
            raw_acres = parcel_acres
        return len(features), raw_acres

    def _geometry_area_acres(self, geometries: list[dict]) -> float:
        if not geometries:
            return 0.0
        areas = self._fetch_json(
            GEOMETRY_AREAS_URL,
            {
                "f": "json",
                "sr": MAP_SPATIAL_REFERENCE,
                "polygons": json.dumps(geometries, separators=(",", ":")),
                "lengthUnit": "9003",
                "areaUnit": json.dumps({"areaUnit": "esriSquareFeet"}, separators=(",", ":")),
                "calculationType": "planar",
            },
        ).get("areas", [])
        return sum(abs(float(area)) for area in areas) / ACRE_SF

    def _render_group_images(
        self,
        parcel: ParcelGeometry,
        group_names: tuple[str, ...],
        temp_dir: Path,
    ) -> list[tuple[str, Path, Path | None]]:
        bbox = self._print_bbox(parcel.extent, EXPORT_WIDTH, EXPORT_HEIGHT)
        images: dict[str, Path] = {}
        max_workers = min(4, max(1, len(group_names)))
        self.progress("Rendering map images")
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(self._render_group_image, parcel, group_name, bbox, temp_dir): group_name
                for group_name in group_names
            }
            for future in as_completed(futures):
                group_name = futures[future]
                images[group_name] = future.result()
                self.progress(f"Rendered {group_name}")

        ordered_pages: list[tuple[str, Path, Path | None]] = []
        for group_name in group_names:
            legend_path = FEMA_LEGEND_PATH if group_name == "FEMA Floodplain" else None
            ordered_pages.append((group_name, images[group_name], legend_path))
        return ordered_pages

    def _render_group_image(
        self,
        parcel: ParcelGeometry,
        group_name: str,
        bbox: tuple[float, float, float, float],
        temp_dir: Path,
    ) -> Path:
        self._check_cancelled()
        map_group = ENVIRONMENTAL_GROUPS[group_name]
        safe_group = safe_file_part(group_name)
        base_path = temp_dir / f"{safe_group} base.png"
        overlay_path = temp_dir / f"{safe_group} overlay.png"
        parcel_path = temp_dir / f"{safe_group} parcel.png"
        output_path = temp_dir / f"{safe_group} final.png"

        self._export_map_image(
            IMAGERY_2025_MAPSERVER_URL,
            bbox,
            base_path,
            transparent=False,
            width=EXPORT_WIDTH,
            height=EXPORT_HEIGHT,
            dpi=EXPORT_DPI,
        )
        self._export_resource_overlay(
            map_group.layer_names,
            bbox,
            overlay_path,
            temp_dir,
            width=EXPORT_WIDTH,
            height=EXPORT_HEIGHT,
            dpi=EXPORT_DPI,
        )
        self._export_map_image(
            PARCEL_MAPSERVER_URL,
            bbox,
            parcel_path,
            layers=(0, 3, 8),
            transparent=True,
            width=EXPORT_WIDTH,
            height=EXPORT_HEIGHT,
            dpi=EXPORT_DPI,
        )
        self._compose_map(
            parcel.geometry,
            bbox,
            base_path,
            overlay_path,
            parcel_path,
            output_path,
            width=EXPORT_WIDTH,
            height=EXPORT_HEIGHT,
        )
        return output_path

    def _export_resource_overlay(
        self,
        layer_names: tuple[str, ...],
        bbox: tuple[float, float, float, float],
        output_path: Path,
        temp_dir: Path,
        width: int,
        height: int,
        dpi: int,
    ) -> None:
        layers_by_service: dict[str, list[int]] = {}
        for name in layer_names:
            layer = ENVIRONMENTAL_LAYER_SOURCES.get(name)
            if layer is None:
                continue
            layers_by_service.setdefault(layer.mapserver_url, []).append(layer.layer_id)

        if not layers_by_service:
            Image.new("RGBA", (width, height), (0, 0, 0, 0)).save(output_path, format="PNG")
            return

        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        for index, (mapserver_url, layer_ids) in enumerate(layers_by_service.items()):
            part_path = temp_dir / f"{output_path.stem} overlay {index}.png"
            self._export_map_image(
                mapserver_url,
                bbox,
                part_path,
                layers=tuple(layer_ids),
                transparent=True,
                width=width,
                height=height,
                dpi=dpi,
            )
            with Image.open(part_path) as part:
                canvas.alpha_composite(part.convert("RGBA"))
        canvas.save(output_path, format="PNG", optimize=False, compress_level=1)

    def _render_preview_bundle(
        self,
        parcel: ParcelGeometry,
        statuses: tuple[ResourcePresence, ...],
        selected_groups: tuple[str, ...],
        include_layers: bool = True,
    ) -> PreviewBundle:
        self.progress("Building live preview" if include_layers else "Building aerial preview")
        bbox = self._print_bbox(
            parcel.extent,
            PREVIEW_WIDTH,
            PREVIEW_HEIGHT,
            context_ratio=PREVIEW_CONTEXT_RATIO,
            min_context_feet=PREVIEW_MIN_CONTEXT_FEET,
        )
        with tempfile.TemporaryDirectory(prefix="environmental_widget_preview_") as temp_name:
            temp_dir = Path(temp_name)
            base_path = temp_dir / "aerial preview.png"
            self._export_map_image(
                IMAGERY_2025_MAPSERVER_URL,
                bbox,
                base_path,
                transparent=False,
                width=PREVIEW_WIDTH,
                height=PREVIEW_HEIGHT,
                dpi=PREVIEW_DPI,
            )
            layer_images = self._render_preview_layers(bbox, temp_dir) if include_layers else {}
            with Image.open(base_path) as base_image:
                base = base_image.convert("RGBA").copy()

        present_layers = {status.name for status in statuses if status.status == "Present"}
        selected_layer_names = tuple(
            dict.fromkeys(
                layer_name
                for group_name in selected_groups
                for layer_name in ENVIRONMENTAL_GROUPS[group_name].layer_names
            )
        )
        default_layers = tuple(name for name in selected_layer_names if name in present_layers and name in layer_images)
        roads = self._query_preview_roads(parcel.geometry, parcel.extent)
        road_overlay = self._road_overlay_image(roads, bbox, PREVIEW_WIDTH, PREVIEW_HEIGHT)
        parcel_outline = self._parcel_outline_image(parcel.geometry, bbox, PREVIEW_WIDTH, PREVIEW_HEIGHT)
        return PreviewBundle(
            base_image=base,
            layer_images=layer_images,
            road_overlay_image=road_overlay,
            parcel_outline_image=parcel_outline,
            default_visible_layers=default_layers,
            parcel_facts=self._parcel_facts(parcel),
            zoning_districts=self._query_zoning_districts(parcel.geometry),
        )

    def _query_preview_roads(
        self,
        parcel_geometry: dict,
        parcel_extent: tuple[float, float, float, float],
    ) -> tuple[RoadFeature, ...]:
        xmin, ymin, xmax, ymax = parcel_extent
        search_geometry = {
            "xmin": xmin - TOUCHING_ROAD_SEARCH_FEET,
            "ymin": ymin - TOUCHING_ROAD_SEARCH_FEET,
            "xmax": xmax + TOUCHING_ROAD_SEARCH_FEET,
            "ymax": ymax + TOUCHING_ROAD_SEARCH_FEET,
            "spatialReference": {"wkid": int(MAP_SPATIAL_REFERENCE)},
        }
        data = self._fetch_json(
            ROADS_LAYER_QUERY_URL,
            {
                "f": "json",
                "where": "LABEL IS NOT NULL",
                "outFields": "LABEL,CLASS",
                "returnGeometry": "true",
                "outSR": MAP_SPATIAL_REFERENCE,
                "geometry": json.dumps(search_geometry, separators=(",", ":")),
                "geometryType": "esriGeometryEnvelope",
                "spatialRel": "esriSpatialRelIntersects",
            },
        )
        roads: list[RoadFeature] = []
        for feature in data.get("features") or []:
            attributes = feature.get("attributes") or {}
            label = " ".join(str(attributes.get("LABEL") or "").split())
            if not label:
                continue
            try:
                road_class = int(attributes.get("CLASS") or 99)
            except (TypeError, ValueError):
                road_class = 99
            paths = []
            for path in (feature.get("geometry") or {}).get("paths", []):
                points = tuple((float(point[0]), float(point[1])) for point in path)
                if len(points) >= 2:
                    paths.append(points)
            if paths:
                road = RoadFeature(label=label, road_class=road_class, paths=tuple(paths))
                if self._road_touches_parcel_frontage(road, parcel_geometry):
                    roads.append(road)
        return tuple(self._dedupe_frontage_roads(roads))

    def _query_zoning_districts(self, parcel_geometry: dict) -> tuple[str, ...]:
        districts: list[str] = []
        seen: set[str] = set()

        for url, fields, code_field, description_field in (
            (ZONING_LAYER_QUERY_URL, "CODE,DESCRIPTION", "CODE", "DESCRIPTION"),
            (MUNICIPAL_ZONING_LAYER_QUERY_URL, "ZONE,ZONE_DESC", "ZONE", "ZONE_DESC"),
        ):
            try:
                data = self._fetch_json(
                    url,
                    {
                        "f": "json",
                        "where": "1=1",
                        "outFields": fields,
                        "returnGeometry": "false",
                        "geometry": json.dumps(parcel_geometry, separators=(",", ":")),
                        "geometryType": "esriGeometryPolygon",
                        "inSR": MAP_SPATIAL_REFERENCE,
                        "spatialRel": "esriSpatialRelIntersects",
                    },
                )
            except RuntimeError:
                continue
            for feature in data.get("features") or []:
                attributes = feature.get("attributes") or {}
                district = self._clean_attribute(attributes.get(code_field))
                if not district:
                    district = self._clean_attribute(attributes.get(description_field))
                if code_field == "ZONE":
                    district = normalize_municipal_zoning_code(district)
                if not district or district.upper() in seen:
                    continue
                seen.add(district.upper())
                districts.append(district.upper())
        if not districts:
            districts.extend(self._query_municipal_zoning_by_point(parcel_geometry, seen))
        if not districts:
            districts.extend(self._query_county_zoning_sublayers(parcel_geometry, seen))
        return tuple(districts)

    def _query_municipal_zoning_by_point(self, parcel_geometry: dict, seen: set[str]) -> tuple[str, ...]:
        districts: list[str] = []
        point = self._representative_point(parcel_geometry)
        try:
            data = self._fetch_json(
                MUNICIPAL_ZONING_LAYER_QUERY_URL,
                {
                    "f": "json",
                    "where": "1=1",
                    "outFields": "ZONE,ZONE_DESC",
                    "returnGeometry": "false",
                    "geometry": json.dumps(point, separators=(",", ":")),
                    "geometryType": "esriGeometryPoint",
                    "inSR": MAP_SPATIAL_REFERENCE,
                    "spatialRel": "esriSpatialRelIntersects",
                },
            )
        except RuntimeError:
            return ()
        for feature in data.get("features") or []:
            attributes = feature.get("attributes") or {}
            district = normalize_municipal_zoning_code(self._clean_attribute(attributes.get("ZONE")))
            if not district:
                district = self._clean_attribute(attributes.get("ZONE_DESC"))
            if not district or district.upper() in seen:
                continue
            seen.add(district.upper())
            districts.append(district.upper())
        return tuple(districts)

    def _query_county_zoning_sublayers(self, parcel_geometry: dict, seen: set[str]) -> tuple[str, ...]:
        districts: list[str] = []
        point = self._representative_point(parcel_geometry)
        for layer_id in COUNTY_ZONING_FALLBACK_LAYER_IDS:
            try:
                data = self._fetch_json(
                    f"{NCC_ZONING_MAPSERVER_URL}/{layer_id}/query",
                    {
                        "f": "json",
                        "where": "1=1",
                        "outFields": "CODE,DESCRIPTION",
                        "returnGeometry": "false",
                        "geometry": json.dumps(point, separators=(",", ":")),
                        "geometryType": "esriGeometryPoint",
                        "inSR": MAP_SPATIAL_REFERENCE,
                        "spatialRel": "esriSpatialRelIntersects",
                    },
                )
            except RuntimeError:
                continue
            for feature in data.get("features") or []:
                attributes = feature.get("attributes") or {}
                district = self._clean_attribute(attributes.get("CODE")) or self._clean_attribute(attributes.get("DESCRIPTION"))
                if not district or district.upper() in seen:
                    continue
                seen.add(district.upper())
                districts.append(district.upper())
        return tuple(districts)

    def _representative_point(self, geometry: dict) -> dict:
        rings = geometry.get("rings") or []
        ring = max(rings or [[]], key=len)
        if not ring:
            return {"x": 0, "y": 0, "spatialReference": {"wkid": int(MAP_SPATIAL_REFERENCE)}}
        x = sum(float(point[0]) for point in ring) / len(ring)
        y = sum(float(point[1]) for point in ring) / len(ring)
        return {"x": x, "y": y, "spatialReference": {"wkid": int(MAP_SPATIAL_REFERENCE)}}

    def _road_touches_parcel_frontage(self, road: RoadFeature, parcel_geometry: dict) -> bool:
        parcel_segments = self._geometry_segments(parcel_geometry)
        if not parcel_segments:
            return False
        for road_path in road.paths:
            for index in range(1, len(road_path)):
                road_segment = (road_path[index - 1], road_path[index])
                for parcel_segment in parcel_segments:
                    if self._segment_distance(road_segment, parcel_segment) <= TOUCHING_ROAD_SEARCH_FEET:
                        return True
        return False

    def _dedupe_frontage_roads(self, roads: list[RoadFeature]) -> list[RoadFeature]:
        chosen: dict[str, RoadFeature] = {}
        for road in sorted(roads, key=lambda item: (item.road_class, item.label)):
            key = road.label.upper()
            if key not in chosen:
                chosen[key] = road
        return list(chosen.values())[:6]

    def _geometry_segments(self, geometry: dict) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for ring in geometry.get("rings", []):
            points = [(float(point[0]), float(point[1])) for point in ring]
            for index in range(1, len(points)):
                segments.append((points[index - 1], points[index]))
        return segments

    def _segment_distance(
        self,
        first: tuple[tuple[float, float], tuple[float, float]],
        second: tuple[tuple[float, float], tuple[float, float]],
    ) -> float:
        if self._segments_intersect(first, second):
            return 0.0
        return min(
            self._point_segment_distance(first[0], second),
            self._point_segment_distance(first[1], second),
            self._point_segment_distance(second[0], first),
            self._point_segment_distance(second[1], first),
        )

    def _segments_intersect(
        self,
        first: tuple[tuple[float, float], tuple[float, float]],
        second: tuple[tuple[float, float], tuple[float, float]],
    ) -> bool:
        def orientation(a, b, c) -> float:
            return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

        a, b = first
        c, d = second
        o1 = orientation(a, b, c)
        o2 = orientation(a, b, d)
        o3 = orientation(c, d, a)
        o4 = orientation(c, d, b)
        return (o1 == 0 or o2 == 0 or o1 * o2 < 0) and (o3 == 0 or o4 == 0 or o3 * o4 < 0)

    def _point_segment_distance(
        self,
        point: tuple[float, float],
        segment: tuple[tuple[float, float], tuple[float, float]],
    ) -> float:
        (x, y) = point
        (x1, y1), (x2, y2) = segment
        dx = x2 - x1
        dy = y2 - y1
        if dx == 0 and dy == 0:
            return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
        ratio = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
        closest_x = x1 + ratio * dx
        closest_y = y1 + ratio * dy
        return ((x - closest_x) ** 2 + (y - closest_y) ** 2) ** 0.5

    def _render_preview_layers(
        self,
        bbox: tuple[float, float, float, float],
        temp_dir: Path,
    ) -> dict[str, Image.Image]:
        layer_images: dict[str, Image.Image] = {}
        mapped_layers = tuple(name for name in RESOURCE_STATUS_ORDER if name in ENVIRONMENTAL_LAYER_SOURCES)

        def render(name: str) -> tuple[str, Image.Image]:
            layer = ENVIRONMENTAL_LAYER_SOURCES[name]
            path = temp_dir / f"{safe_file_part(name)}.png"
            self._export_map_image(
                layer.mapserver_url,
                bbox,
                path,
                layers=(layer.layer_id,),
                transparent=True,
                width=PREVIEW_WIDTH,
                height=PREVIEW_HEIGHT,
                dpi=PREVIEW_DPI,
            )
            with Image.open(path) as image:
                return name, image.convert("RGBA").copy()

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(render, name): name for name in mapped_layers}
            for future in as_completed(futures):
                name, image = future.result()
                layer_images[name] = image
        return layer_images

    def _export_map_image(
        self,
        mapserver_url: str,
        bbox: tuple[float, float, float, float],
        output_path: Path,
        layers: tuple[int, ...] = (),
        transparent: bool = True,
        width: int = EXPORT_WIDTH,
        height: int = EXPORT_HEIGHT,
        dpi: int = EXPORT_DPI,
    ) -> None:
        self._check_cancelled()
        params = {
            "f": "json",
            "bbox": ",".join(f"{value:.3f}" for value in bbox),
            "bboxSR": MAP_SPATIAL_REFERENCE,
            "imageSR": MAP_SPATIAL_REFERENCE,
            "size": f"{width},{height}",
            "dpi": str(dpi),
            "format": "png32",
            "transparent": "true" if transparent else "false",
        }
        if layers:
            params["layers"] = "show:" + ",".join(str(layer_id) for layer_id in layers)

        data = self._fetch_json(f"{mapserver_url}/export", params)
        href = data.get("href")
        if not href:
            error = data.get("error") or data
            raise RuntimeError(f"Map export failed: {error}")
        self._download_file(str(href), output_path)

    def _compose_map(
        self,
        parcel_geometry: dict,
        bbox: tuple[float, float, float, float],
        base_path: Path,
        overlay_path: Path,
        parcel_path: Path,
        output_path: Path,
        width: int,
        height: int,
    ) -> None:
        with Image.open(base_path) as base_image:
            canvas = base_image.convert("RGBA")
        for layer_path in (overlay_path, parcel_path):
            with Image.open(layer_path) as layer_image:
                canvas.alpha_composite(layer_image.convert("RGBA"))

        draw = ImageDraw.Draw(canvas, "RGBA")
        for ring in parcel_geometry.get("rings", []):
            points = [self._map_point_to_pixel(point, bbox, width, height) for point in ring]
            if len(points) >= 2:
                draw.line(points, fill=(24, 220, 170, 255), width=8, joint="curve")
                draw.line(points, fill=(3, 18, 16, 220), width=3, joint="curve")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.convert("RGB").save(output_path, format="PNG", optimize=False, compress_level=1)

    def _write_pdfs(self, image_pages: list[tuple[str, Path, Path | None]]) -> list[Path]:
        pdf_paths: list[Path] = []
        parcel_file_part = safe_file_part(self.parcel_number or self.search_parcel_number)
        combined_pages: list[tuple[Path, Path | None]] = []
        for group_name, image_path, legend_path in image_pages:
            pdf_path = self.destination / f"{parcel_file_part} {safe_file_part(group_name)} Map.pdf"
            self.progress(f"Writing {group_name} PDF")
            image_to_full_bleed_pdf(image_path, pdf_path, overlay_image_path=legend_path)
            pdf_paths.append(pdf_path)
            combined_pages.append((image_path, legend_path))

        combined_path = self.destination / f"{parcel_file_part} Environmental Map.pdf"
        self.progress("Writing combined environmental PDF")
        images_to_full_bleed_pdf(combined_pages, combined_path)
        pdf_paths.append(combined_path)
        return pdf_paths

    def _fetch_json(self, url: str, params: dict[str, str]) -> dict:
        encoded = urllib.parse.urlencode(params).encode("utf-8")
        request = urllib.request.Request(url, data=encoded, method="POST")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)

    def _download_file(self, url: str, output_path: Path) -> None:
        request = urllib.request.Request(url)
        with urllib.request.urlopen(request, timeout=60) as response:
            output_path.write_bytes(response.read())

    def _print_bbox(
        self,
        extent: tuple[float, float, float, float],
        width_pixels: int,
        height_pixels: int,
        context_ratio: float = PARCEL_CONTEXT_RATIO,
        min_context_feet: float = MIN_CONTEXT_FEET,
    ) -> tuple[float, float, float, float]:
        xmin, ymin, xmax, ymax = extent
        width = max(xmax - xmin, 1.0)
        height = max(ymax - ymin, 1.0)
        pad = max(max(width, height) * context_ratio, min_context_feet)
        xmin -= pad
        ymin -= pad
        xmax += pad
        ymax += pad

        target_ratio = width_pixels / height_pixels
        width = xmax - xmin
        height = ymax - ymin
        current_ratio = width / height
        if current_ratio < target_ratio:
            extra = (height * target_ratio - width) / 2
            xmin -= extra
            xmax += extra
        else:
            extra = (width / target_ratio - height) / 2
            ymin -= extra
            ymax += extra
        return xmin, ymin, xmax, ymax

    def _geometry_extent(self, geometry: dict) -> tuple[float, float, float, float]:
        points = [point for ring in geometry.get("rings", []) for point in ring]
        if not points:
            raise RuntimeError("Parcel geometry has no polygon rings.")
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        return min(xs), min(ys), max(xs), max(ys)

    def _road_overlay_image(
        self,
        roads: tuple[RoadFeature, ...],
        bbox: tuple[float, float, float, float],
        width: int,
        height: int,
    ) -> Image.Image:
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay, "RGBA")
        label_font = self._preview_font(32)
        placed_labels: set[str] = set()

        for road in sorted(roads, key=lambda item: (item.road_class, item.label), reverse=True):
            line_width = self._road_line_width(road.road_class)
            for path in road.paths:
                points = [self._map_point_to_pixel([x, y], bbox, width, height) for x, y in path]
                if len(points) >= 2:
                    draw.line(points, fill=(22, 26, 29, 210), width=line_width + 3, joint="curve")
                    draw.line(points, fill=(238, 242, 238, 230), width=line_width, joint="curve")

        for road in roads:
            if road.label in placed_labels or len(placed_labels) >= 14:
                continue
            label_placement = self._road_label_placement(road, bbox, width, height)
            if label_placement is None:
                continue
            x, y, angle = label_placement
            text = road.label.title()
            label_image = self._rotated_label_image(text, label_font, angle)
            x = int(max(8, min(width - label_image.width - 8, x - label_image.width / 2)))
            y = int(max(8, min(height - label_image.height - 8, y - label_image.height / 2)))
            overlay.alpha_composite(label_image, (x, y))
            placed_labels.add(road.label)
        return overlay

    def _road_label_placement(
        self,
        road: RoadFeature,
        bbox: tuple[float, float, float, float],
        width: int,
        height: int,
    ) -> tuple[float, float, float] | None:
        segment = self._best_label_segment(road)
        if segment is None:
            return None
        start, end = segment
        x1, y1 = self._map_point_to_pixel([start[0], start[1]], bbox, width, height)
        x2, y2 = self._map_point_to_pixel([end[0], end[1]], bbox, width, height)
        angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
        if angle > 90:
            angle -= 180
        elif angle < -90:
            angle += 180
        return (x1 + x2) / 2, (y1 + y2) / 2, angle

    def _best_label_segment(
        self,
        road: RoadFeature,
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        best: tuple[tuple[float, float], tuple[float, float]] | None = None
        best_length = 0.0
        for path in road.paths:
            for index in range(1, len(path)):
                start = path[index - 1]
                end = path[index]
                length = ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
                if length > best_length:
                    best = (start, end)
                    best_length = length
        return best

    def _rotated_label_image(
        self,
        text: str,
        font: ImageFont.ImageFont,
        angle: float,
    ) -> Image.Image:
        scratch = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        scratch_draw = ImageDraw.Draw(scratch)
        box = scratch_draw.textbbox((0, 0), text, font=font, stroke_width=6)
        text_width = box[2] - box[0] + 24
        text_height = box[3] - box[1] + 20
        label = Image.new("RGBA", (text_width, text_height), (0, 0, 0, 0))
        label_draw = ImageDraw.Draw(label)
        label_draw.text(
            (12, 7),
            text,
            font=font,
            fill=(255, 255, 255, 255),
            stroke_width=6,
            stroke_fill=(0, 0, 0, 255),
        )
        return label.rotate(-angle, expand=True, resample=Image.Resampling.BICUBIC)

    def _road_line_width(self, road_class: int) -> int:
        if road_class <= 1:
            return 7
        if road_class <= 3:
            return 5
        if road_class <= 5:
            return 4
        return 3

    def _preview_font(self, size: int) -> ImageFont.ImageFont:
        try:
            for font_path in ARIAL_BLACK_FONT_CANDIDATES:
                if font_path.exists():
                    return ImageFont.truetype(str(font_path), size=size)
            if NUNITO_FONT_PATH.exists():
                return ImageFont.truetype(str(NUNITO_FONT_PATH), size=size)
        except OSError:
            LOGGER.exception("Could not load preview label font")
        return ImageFont.load_default()

    def _parcel_facts(self, parcel: ParcelGeometry) -> dict[str, str]:
        attributes = parcel.attributes
        address_parts = [
            self._clean_attribute(attributes.get("ADDRESS")),
            self._clean_attribute(attributes.get("PROPCITY")),
            self._clean_attribute(attributes.get("PROPSTATE")),
            self._clean_attribute(attributes.get("PROPZIP")),
        ]
        return {
            "Parcel": self._clean_attribute(attributes.get("PARCELNO")) or parcel.parcel_number,
            "Address": ", ".join(part for part in address_parts if part),
            "Owner": self._clean_attribute(attributes.get("CNTCTLAST")),
        }

    def _clean_attribute(self, value: object) -> str:
        if value is None:
            return ""
        return " ".join(str(value).split()).strip(" ,-")

    def _map_point_to_pixel(
        self,
        point: list[float],
        bbox: tuple[float, float, float, float],
        width: int,
        height: int,
    ) -> tuple[float, float]:
        xmin, ymin, xmax, ymax = bbox
        x = (float(point[0]) - xmin) / (xmax - xmin) * width
        y = height - ((float(point[1]) - ymin) / (ymax - ymin) * height)
        return x, y

    def _parcel_outline_image(
        self,
        parcel_geometry: dict,
        bbox: tuple[float, float, float, float],
        width: int,
        height: int,
    ) -> Image.Image:
        outline = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(outline, "RGBA")
        for ring in parcel_geometry.get("rings", []):
            points = [self._map_point_to_pixel(point, bbox, width, height) for point in ring]
            if len(points) >= 2:
                draw.line(points, fill=(0, 8, 7, 230), width=6, joint="curve")
                draw.line(points, fill=(34, 235, 178, 255), width=3, joint="curve")
        return outline

    def _check_cancelled(self) -> None:
        if self.stop_event.is_set():
            raise RuntimeError("Run cancelled")
