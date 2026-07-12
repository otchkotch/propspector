from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ALL_RESOURCES_GROUP = "All Resources"

PARCEL_LAYER_QUERY_URL = "https://gis.nccde.org/agsserver/rest/services/BaseMaps/Base_Layers/MapServer/0/query"
PARCEL_MAPSERVER_URL = "https://gis.nccde.org/agsserver/rest/services/BaseMaps/Base_Layers/MapServer"
ENVIRONMENTAL_MAPSERVER_URL = "https://gis.nccde.org/agsserver/rest/services/BaseMaps/Environmental/MapServer"
WRPA_MAPSERVER_URL = "https://gis.nccde.org/agsserver/rest/services/BaseMaps/WRPA/MapServer"
IMAGERY_2025_MAPSERVER_URL = "https://gis.nccde.org/agsserver/rest/services/Imagery/Imagery_2025/MapServer"
FEMA_LEGEND_PATH = Path(__file__).with_name("assets") / "fema_layers_legend.png"


@dataclass(frozen=True)
class ResourceLayer:
    name: str
    mapserver_url: str
    layer_id: int


@dataclass(frozen=True)
class MapGroup:
    name: str
    layer_names: tuple[str, ...]

    @property
    def layer_ids(self) -> tuple[int, ...]:
        return tuple(ENVIRONMENTAL_LAYER_IDS[name] for name in self.layer_names)


@dataclass(frozen=True)
class ResourcePresence:
    name: str
    status: str
    count: int | None = None
    raw_acres: float | None = None
    error: str = ""


ENVIRONMENTAL_LAYER_IDS: dict[str, int] = {
    "Watersheds": 1,
    "FEMA 100-year Floodplain (1 PCT Annual Chance)": 9,
    "FEMA 500-year Floodplain (0.2 PCT Annual Chance)": 10,
    "NHD Lines": 12,
    "NHD Waterbodies": 13,
    "Swamp/Marsh": 14,
    "Forests": 15,
    "Erosion Prone Soils": 16,
    "Erosion Prone Soils/Slopes": 16,
    "State Wetlands": 17,
    "National Wetlands": 18,
    "Critical Natural Areas": 19,
    "Coastal Zone": 20,
    "WRPA Recharge Areas": 0,
    "WRPA Reservoir Watersheds": 34,
    "WRPA Class A Wellhead 150ft Radius": 2,
    "WRPA Class A Wellhead": 3,
    "WRPA Class A Transient Non-Community Wells": 4,
    "WRPA Class A Non-Transient Non-Community Wells": 5,
    "WRPA Class B Wellhead": 6,
    "WRPA Class C Wellhead": 7,
    "Cockeysville Formation": 8,
    "Cockeysville Drainage Basin": 9,
    "WRPA Erosion Prone Soils": 10,
    "WRPA Floodplains": 11,
}


ENVIRONMENTAL_LAYER_SOURCES: dict[str, ResourceLayer] = {
    name: ResourceLayer(name, ENVIRONMENTAL_MAPSERVER_URL, layer_id)
    for name, layer_id in ENVIRONMENTAL_LAYER_IDS.items()
}
ENVIRONMENTAL_LAYER_SOURCES.update(
    {
        "WRPA Recharge Areas": ResourceLayer("WRPA Recharge Areas", WRPA_MAPSERVER_URL, 0),
        "WRPA Reservoir Watersheds": ResourceLayer("WRPA Reservoir Watersheds", WRPA_MAPSERVER_URL, 34),
        "WRPA Class A Wellhead 150ft Radius": ResourceLayer("WRPA Class A Wellhead 150ft Radius", WRPA_MAPSERVER_URL, 2),
        "WRPA Class A Wellhead": ResourceLayer("WRPA Class A Wellhead", WRPA_MAPSERVER_URL, 3),
        "WRPA Class A Transient Non-Community Wells": ResourceLayer("WRPA Class A Transient Non-Community Wells", WRPA_MAPSERVER_URL, 4),
        "WRPA Class A Non-Transient Non-Community Wells": ResourceLayer("WRPA Class A Non-Transient Non-Community Wells", WRPA_MAPSERVER_URL, 5),
        "WRPA Class B Wellhead": ResourceLayer("WRPA Class B Wellhead", WRPA_MAPSERVER_URL, 6),
        "WRPA Class C Wellhead": ResourceLayer("WRPA Class C Wellhead", WRPA_MAPSERVER_URL, 7),
        "Cockeysville Formation": ResourceLayer("Cockeysville Formation", WRPA_MAPSERVER_URL, 8),
        "Cockeysville Drainage Basin": ResourceLayer("Cockeysville Drainage Basin", WRPA_MAPSERVER_URL, 9),
        "WRPA Erosion Prone Soils": ResourceLayer("WRPA Erosion Prone Soils", WRPA_MAPSERVER_URL, 10),
        "WRPA Floodplains": ResourceLayer("WRPA Floodplains", WRPA_MAPSERVER_URL, 11),
    }
)


ENVIRONMENTAL_LAYERS = (
    "NHD Lines",
    "NHD Waterbodies",
    "Swamp/Marsh",
    "State Wetlands",
    "National Wetlands",
    "Forests",
    "Erosion Prone Soils/Slopes",
    "Critical Natural Areas",
    "Coastal Zone",
    "WRPA Floodplains",
    "FEMA 100-year Floodplain (1 PCT Annual Chance)",
    "FEMA 500-year Floodplain (0.2 PCT Annual Chance)",
    "Coastal Flooding Evacuation Zones",
    "WRPA Recharge Areas",
    "WRPA Reservoir Watersheds",
    "WRPA Class A Wellhead 150ft Radius",
    "WRPA Class A Wellhead",
    "WRPA Class A Transient Non-Community Wells",
    "WRPA Class A Non-Transient Non-Community Wells",
    "WRPA Class B Wellhead",
    "WRPA Class C Wellhead",
    "Cockeysville Formation",
    "Cockeysville Drainage Basin",
    "WRPA Erosion Prone Soils",
    "WRPA Floodplains",
)


ENVIRONMENTAL_GROUPS: dict[str, MapGroup] = {
    "FEMA Floodplain": MapGroup(
        "FEMA Floodplain",
        (
            "FEMA 100-year Floodplain (1 PCT Annual Chance)",
            "FEMA 500-year Floodplain (0.2 PCT Annual Chance)",
        ),
    ),
    "NHD Swamp Marsh State Wetlands": MapGroup(
        "NHD Swamp Marsh State Wetlands",
        (
            "NHD Lines",
            "NHD Waterbodies",
            "Swamp/Marsh",
            "State Wetlands",
        ),
    ),
    "Forests NHD": MapGroup(
        "Forests NHD",
        (
            "Forests",
            "NHD Lines",
            "NHD Waterbodies",
        ),
    ),
    "Critical Natural Areas Coastal Zone": MapGroup(
        "Critical Natural Areas Coastal Zone",
        (
            "Critical Natural Areas",
            "Coastal Zone",
        ),
    ),
    "Erosion Prone Soils Slopes": MapGroup(
        "Erosion Prone Soils Slopes",
        (
            "Erosion Prone Soils/Slopes",
            "WRPA Erosion Prone Soils",
        ),
    ),
    "Water Resources": MapGroup(
        "Water Resources",
        (
            "Watersheds",
            "WRPA Recharge Areas",
            "WRPA Reservoir Watersheds",
            "WRPA Class A Wellhead 150ft Radius",
            "WRPA Class A Wellhead",
            "WRPA Class A Transient Non-Community Wells",
            "WRPA Class A Non-Transient Non-Community Wells",
            "WRPA Class B Wellhead",
            "WRPA Class C Wellhead",
            "Cockeysville Formation",
            "Cockeysville Drainage Basin",
            "WRPA Erosion Prone Soils",
            "WRPA Floodplains",
        ),
    ),
}


ENVIRONMENTAL_MENU_GROUPS: tuple[str, ...] = (ALL_RESOURCES_GROUP, *ENVIRONMENTAL_GROUPS.keys())


RESOURCE_STATUS_ORDER: tuple[str, ...] = (
    "NHD Lines",
    "NHD Waterbodies",
    "Swamp/Marsh",
    "State Wetlands",
    "Forests",
    "Erosion Prone Soils/Slopes",
    "Critical Natural Areas",
    "Coastal Zone",
    "Watersheds",
    "WRPA Recharge Areas",
    "WRPA Reservoir Watersheds",
    "WRPA Class A Wellhead 150ft Radius",
    "WRPA Class A Wellhead",
    "WRPA Class A Transient Non-Community Wells",
    "WRPA Class A Non-Transient Non-Community Wells",
    "WRPA Class B Wellhead",
    "WRPA Class C Wellhead",
    "Cockeysville Formation",
    "Cockeysville Drainage Basin",
    "WRPA Erosion Prone Soils",
    "WRPA Floodplains",
    "FEMA 100-year Floodplain (1 PCT Annual Chance)",
    "FEMA 500-year Floodplain (0.2 PCT Annual Chance)",
)
