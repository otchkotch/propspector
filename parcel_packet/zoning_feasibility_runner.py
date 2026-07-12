from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
import math

from .municipal_bots import build_municipal_profile, district_label, normalize_municipal_zoning_code
from .parcel_lookup import address_where, fallback_address_where, parcel_key, parcel_where, split_parcel_inputs


Progress = Callable[[str], None]

MAP_SPATIAL_REFERENCE = "102657"
PARCEL_QUERY_URL = "https://gis.nccde.org/agsserver/rest/services/BaseMaps/Base_Layers/MapServer/0/query"
MUNICIPALITY_QUERY_URL = "https://gis.nccde.org/agsserver/rest/services/BaseMaps/Base_Layers/MapServer/2/query"
COUNTY_ZONING_QUERY_URL = "https://gis.nccde.org/agsserver/rest/services/BaseMaps/Zoning/MapServer/6/query"
NCC_ZONING_MAPSERVER_URL = "https://gis.nccde.org/agsserver/rest/services/BaseMaps/NCC_Zoning/MapServer"
MUNICIPAL_ZONING_QUERY_URL = "https://gis.nccde.org/agsserver/rest/services/BaseMaps/NCC_Zoning/MapServer/4/query"
COUNTY_ZONING_URL_QUERY_URL = "https://gis.nccde.org/agsserver/rest/services/BaseMaps/Zoning/MapServer/10/query"

COUNTY_CODE_HOME = "https://library.municode.com/de/new_castle_county/codes/code_of_ordinances"
MUNICODE_API_BASE = "https://library.municode.com/api"
NCC_MUNICODE_PRODUCT_ID = 14845
NCC_USE_TABLE_NODE_ID = "CH40UNDECO_ART3USRE_S40.03.110USTA"
NCC_BULK_STANDARDS_NODE_ID = "CH40UNDECO_ART4DIINBUST_S40.04.110DIBUST"
NCC_USE_DEFINITIONS_NODE_ID = "CH40UNDECO_ART33DE_DIV40.33.200USDE"
GEOMETRY_INTERSECT_URL = "https://gis.nccde.org/agsserver/rest/services/Utilities/Geometry/GeometryServer/intersect"
GEOMETRY_AREAS_URL = "https://gis.nccde.org/agsserver/rest/services/Utilities/Geometry/GeometryServer/areasAndLengths"
GEOMETRY_DIFFERENCE_URL = "https://gis.nccde.org/agsserver/rest/services/Utilities/Geometry/GeometryServer/difference"
GEOMETRY_UNION_URL = "https://gis.nccde.org/agsserver/rest/services/Utilities/Geometry/GeometryServer/union"
ENVIRONMENTAL_MAPSERVER_URL = "https://gis.nccde.org/agsserver/rest/services/BaseMaps/Environmental/MapServer"
WRPA_MAPSERVER_URL = "https://gis.nccde.org/agsserver/rest/services/BaseMaps/WRPA/MapServer"
ACRE_SF = 43560.0

APARTMENT_RENT_MIX: tuple[tuple[str, float, int, int], ...] = (
    ("studio", 0.05, 1300, 1650),
    ("1BR", 0.45, 1550, 1950),
    ("2BR", 0.40, 1850, 2350),
    ("3BR", 0.10, 2300, 2900),
)

APARTMENT_UNIT_SIZE_MIX: tuple[tuple[str, float, int], ...] = (
    ("studio", 0.05, 550),
    ("1BR", 0.45, 750),
    ("2BR", 0.40, 1050),
    ("3BR", 0.10, 1300),
)

APARTMENT_PROGRAM_GFA_UTILIZATION = 0.90
MIXED_USE_PROGRAM_GFA_UTILIZATION = 1.00
MIXED_USE_COMMERCIAL_GFA_SHARE = 0.12
MIXED_USE_RESIDENTIAL_GROSS_EFFICIENCY = 0.85
APARTMENT_PARKING_SPACES_PER_UNIT = 1.75
SURFACE_PARKING_AREA_PER_SPACE_SF = 330
APARTMENT_BUILDING_FOOTPRINT_SHARE = 0.24
APARTMENT_SITE_SUPPORT_FACTOR = 0.82
COMMERCIAL_PARKING_SPACES_PER_1000_SF = 4.0
FIRE_ACCESS_SITE_FACTOR = 0.92
NONRESIDENTIAL_SITE_SUPPORT_FACTOR = 0.86
NONRESIDENTIAL_BUILDING_FOOTPRINT_SHARE = 0.30

NONRESIDENTIAL_PARKING_RATIOS: dict[str, float] = {
    "office": 3.5,
    "commercial": 4.0,
    "commercial_retail": 4.0,
    "restaurant": 8.0,
    "commercial_lodging": 1.2,
    "heavy_retail": 3.0,
    "industrial": 1.0,
    "mixed_use": COMMERCIAL_PARKING_SPACES_PER_1000_SF,
    "institutional_regional": 3.0,
    "institutional_neighborhood": 3.0,
    "institutional_residential": 2.0,
    "hospital": 4.0,
    "school": 2.5,
    "college": 3.0,
    "other_permitted": 3.0,
    "custom": 3.0,
    "solar": 0.2,
}

COMMERCIAL_RENT_RANGES: dict[str, tuple[int, int, str]] = {
    "office": (18, 30, "office/professional GFA"),
    "commercial": (20, 36, "retail/commercial GFA"),
    "retail": (20, 36, "retail/commercial GFA"),
    "restaurant": (20, 36, "restaurant/commercial GFA"),
    "lodging": (18, 34, "lodging GFA"),
    "industrial": (8, 14, "industrial GFA"),
    "default": (18, 30, "general commercial GFA"),
}

VALUE_SCREEN_METHOD_LINES: tuple[str, ...] = (
    "Value screen is a planning-level gross revenue proxy for comparing zoning options, not an appraisal or pro forma.",
    "Apartment screen uses a blended bedroom mix: 5% studio, 45% 1BR, 40% 2BR, 10% 3BR. The mix favors mostly 1BR/2BR units because those usually carry the widest renter demand and efficient parking/building layouts; 3BR units are retained for family demand but kept lower.",
    "Apartment rents use screening ranges by bedroom: studio $1,300-$1,650/mo, 1BR $1,550-$1,950/mo, 2BR $1,850-$2,350/mo, 3BR $2,300-$2,900/mo. HUD Fair Market Rent data is the public baseline; the range is widened upward to represent market feasibility screening rather than subsidy-only rent.",
    "Apartment screens are capped by both outdoor-area support and a GFA-based residential program. The GFA cap uses the applicable nonresidential/mixed-use bulk table row, a 90% program utilization factor, and the bedroom-size mix.",
    "Apartment and mixed-use screens also reserve site area for surface parking, drive aisles, fire-lane access, internal circulation, sidewalks, stormwater, and open-space/landscape obligations. This moderates code-theoretical GFA into a buildable program estimate.",
    "Nonresidential GFA screens are also capped by a surface-parking/fire-access site-support model. The ratio varies by use, so high-parking uses like restaurants are moderated more aggressively than industrial or solar/utility-style uses.",
    "Mixed use does not double-count full GFA plus apartment units. It allocates the mixed-use GFA envelope into a modest commercial component and residential building program, then caps the residential units by bedroom mix, outdoor-area support, and site support.",
    "Commercial GFA uses annual rent per sf assumptions: office $18-$30, retail/commercial $20-$36, lodging $18-$34, industrial $8-$14. These are deliberately conservative planning ranges until a live broker/CoStar-style market feed is added.",
    "Single-family lot screens use $90k-$180k per finished lot as a rough sale-value proxy and should be replaced with subdivision-specific comp research for client-facing work.",
)

VALUE_SCREEN_SOURCE_LINES: tuple[str, ...] = (
    "HUD Fair Market Rents: https://www.huduser.gov/portal/datasets/fmr.html",
    "NMHC apartment stock/unit mix context: https://www.nmhc.org/research-insight/quick-facts-figures/quick-facts-apartment-stock/",
)

YIELD_PLANNING_DISCLAIMER = (
    "Development yield is a planning-level estimate. Residential unit counts are modeled within the gross floor area "
    "envelope using code-derived and programmatic assumptions. Results should be verified against recorded plans, "
    "approvals, conservancy requirements, parking, stormwater, agency review, and final engineering."
)



@dataclass(frozen=True)
class ParcelRecord:
    parcel_number: str
    address: str
    owner: str
    incorporated_hint: str
    lot_size: float | None
    frontage: float | None
    depth: float | None
    geometry: dict


@dataclass(frozen=True)
class ZoningDistrict:
    code: str
    description: str
    source_url: str = ""
    map_url: str = ""


@dataclass(frozen=True)
class ZoningCoverage:
    district: ZoningDistrict
    acres: float
    percent: float


@dataclass(frozen=True)
class FeasibilityResult:
    status: str
    confidence: str
    summary: str
    details: tuple[str, ...]
    standards: tuple[str, ...]
    sources: tuple[str, ...]
    parcel: ParcelRecord
    municipality: str
    zoning_districts: tuple[ZoningDistrict, ...]
    parcel_area_sf: float
    shape_efficiency: float
    recommendations: tuple[YieldRecommendation, ...]
    protected_resources: tuple[ProtectedResourceResult, ...]
    capacity_matrix: CapacityMatrix | None = None


@dataclass(frozen=True)
class ProgramScenario:
    title: str
    modeled_units: int | None
    envelope_gfa: int | None
    residential_gfa: int | None
    commercial_gfa: int | None
    accessory_gfa: int | None
    total_program_gfa: int | None
    caveat: str


@dataclass(frozen=True)
class YieldRecommendation:
    development_option: str
    status: str
    conservative_yield: int | None
    gross_area_yield: int | None
    limiting_factors: tuple[str, ...]
    note: str
    market_value_low: int | None = None
    market_value_high: int | None = None
    market_basis: str = ""
    program_scenario: ProgramScenario | None = None


@dataclass(frozen=True)
class ProtectedResourceResult:
    name: str
    measured_acres: float
    protected_acres: float
    ratio: float
    source: str
    note: str = ""


@dataclass(frozen=True)
class CapacityMatrix:
    capacity_type: str
    base_site_area_ac: float
    total_resource_land_ac: float
    total_protected_land_ac: float
    total_unrestricted_land_ac: float
    usability_factor: float
    usable_land_ac: float
    site_protected_land_ac: float
    minimum_open_space_ratio: float
    minimum_open_space_ac: float
    required_protected_land_ac: float
    net_buildable_site_area_ac: float
    max_net_density: float
    site_specific_density_yield: float
    max_gross_density: float
    district_density_yield: float
    maximum_yield: int
    minimum_landscape_ratio: float = 0.0
    minimum_landscaped_area_ac: float = 0.0
    buildable_land_district_ac: float = 0.0
    max_net_far: float = 0.0
    max_gross_far: float = 0.0
    site_specific_floor_area_sf: int = 0
    district_floor_area_sf: int = 0
    maximum_floor_area_sf: int = 0


@dataclass(frozen=True)
class BulkStandard:
    zoning_code: str
    use_label: str
    minimum_landscape_ratio: float
    maximum_gross_far: float
    maximum_net_far: float
    permission: str
    minimum_site_area: str
    minimum_lot_area: str
    source: str


@dataclass(frozen=True)
class UseClassification:
    requested_use: str
    official_use: str
    use_key: str
    confidence: str
    rationale: str


class _TableRowParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_cell = False
        self._cell_parts: list[str] = []
        self._row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"}:
            self._in_cell = True
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            text = " ".join(data.split())
            if text:
                self._cell_parts.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell:
            self._row.append(" ".join(self._cell_parts))
            self._in_cell = False
        elif tag == "tr" and self._row:
            self.rows.append(self._row)


class _DefinitionTermParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_italic = False
        self._parts: list[str] = []
        self.terms: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "span" and "ital" in (attributes.get("class") or ""):
            self._in_italic = True
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._in_italic:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._in_italic:
            term = " ".join("".join(self._parts).split()).strip(" .")
            if term:
                self.terms.append(term)
            self._in_italic = False


COUNTY_RESIDENTIAL_STANDARDS: dict[str, dict[str, str]] = {
    "SR": {"min_lot_area": "217800", "min_frontage": "150", "label": "Suburban Reserve", "note": "Typically very low density residential."},
    "SE": {"min_lot_area": "87120", "min_frontage": "150", "label": "Suburban Estate", "note": "Typically estate residential."},
    "S": {"min_lot_area": "21780", "min_frontage": "100", "label": "Suburban", "note": "Typically suburban single-family residential."},
    "NC5": {"min_lot_area": "5000", "min_frontage": "50", "label": "Neighborhood Conservation 5,000", "note": "Small-lot single-family residential."},
    "NC6.5": {"min_lot_area": "6500", "min_frontage": "65", "label": "Neighborhood Conservation 6,500", "note": "Single-family residential."},
    "NC10": {"min_lot_area": "10000", "min_frontage": "80", "label": "Neighborhood Conservation 10,000", "note": "Single-family residential."},
    "NC15": {"min_lot_area": "15000", "min_frontage": "90", "label": "Neighborhood Conservation 15,000", "note": "Single-family residential."},
    "NC21": {"min_lot_area": "21000", "min_frontage": "100", "label": "Neighborhood Conservation 21,000", "note": "Single-family residential."},
    "NC40": {"min_lot_area": "40000", "min_frontage": "125", "label": "Neighborhood Conservation 40,000", "note": "Single-family residential."},
    "NC2A": {"min_lot_area": "87120", "min_frontage": "150", "label": "Neighborhood Conservation 2 acre", "note": "Single-family residential."},
    "NCTH": {"min_lot_area": "0", "label": "Neighborhood Conservation Townhouse", "note": "Townhouse residential district."},
    "NCSD": {"min_lot_area": "0", "label": "Neighborhood Conservation Semi-detached", "note": "Semi-detached residential district."},
    "NCGA": {"min_lot_area": "0", "label": "Neighborhood Conservation Garden Apartment", "note": "Garden apartment residential district."},
    "NCAP": {"min_lot_area": "0", "label": "Neighborhood Conservation Apartment", "note": "Apartment residential district."},
    "NCMM": {"min_lot_area": "0", "label": "Neighborhood Conservation Manufactured/Mobile", "note": "Manufactured/mobile residential district."},
}


COMMERCIAL_RESOURCE_RATIO_DISTRICTS = {"CN", "CR", "ON", "OR", "BP", "I", "HI"}
COUNTY_ZONING_FALLBACK_LAYER_IDS: tuple[int, ...] = (
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


PROTECTED_RESOURCE_SPECS: tuple[dict[str, object], ...] = (
    {"name": "Floodplain / Floodway", "service": ENVIRONMENTAL_MAPSERVER_URL, "layers": (9,), "commercial_ratio": 1.0, "other_ratio": 1.0},
    {"name": "Wetland (see section 10.320)", "service": ENVIRONMENTAL_MAPSERVER_URL, "layers": (14, 17, 18), "commercial_ratio": 1.0, "other_ratio": 1.0},
    {"name": "Cockeysville Formation - WRPA", "service": WRPA_MAPSERVER_URL, "layers": (8,), "commercial_ratio": 0.5, "other_ratio": 0.5},
    {"name": "Cockeysville Formation - Drainage Area - WRPA", "service": WRPA_MAPSERVER_URL, "layers": (9,), "commercial_ratio": 0.5, "other_ratio": 0.5},
    {"name": "Wellhead - WRPA Class A", "service": WRPA_MAPSERVER_URL, "layers": (2, 3, 4, 5), "commercial_ratio": 1.0, "other_ratio": 1.0},
    {"name": "Wellhead - WRPA Class B & C", "service": WRPA_MAPSERVER_URL, "layers": (6, 7), "commercial_ratio": 0.5, "other_ratio": 0.5},
    {"name": "Recharge Areas - WRPA", "service": WRPA_MAPSERVER_URL, "layers": (0,), "commercial_ratio": 0.5, "other_ratio": 0.5},
    {"name": "Slope or Geologic Sites - CNA", "service": ENVIRONMENTAL_MAPSERVER_URL, "layers": (19,), "commercial_ratio": 1.0, "other_ratio": 1.0},
    {"name": "Forests, assumed Tier 3", "service": ENVIRONMENTAL_MAPSERVER_URL, "layers": (15,), "commercial_ratio": 0.1, "other_ratio": 0.3, "note": "Forest areas require delineation and classification. This study assumes Tier 3 forest for all forested areas."},
)


UNMAPPED_PROTECTED_RESOURCES: tuple[str, ...] = (
    "Riparian Buffer",
    "Drainageways",
    "Sinkhole",
    "Steep Slopes (>25%)",
    "Steep Slopes (15-25%)",
    "Rare Species Site - CNA",
    "Historic",
)


COUNTY_RESIDENTIAL_CAPACITY_STANDARDS: dict[str, dict[str, float]] = {
    "SR": {"usability": 0.015, "open_space": 0.75, "net_density": 0.20, "gross_density": 0.20},
    "SE": {"usability": 0.022, "open_space": 0.70, "net_density": 0.50, "gross_density": 0.50},
    "NC2A": {"usability": 0.022, "open_space": 0.70, "net_density": 0.50, "gross_density": 0.50},
    "S": {"usability": 0.049, "open_space": 0.50, "net_density": 1.30, "gross_density": 1.00},
    "NC40": {"usability": 0.049, "open_space": 0.50, "net_density": 1.30, "gross_density": 1.00},
    "NC21": {"usability": 0.049, "open_space": 0.50, "net_density": 1.30, "gross_density": 1.00},
    "NC15": {"usability": 0.049, "open_space": 0.50, "net_density": 1.30, "gross_density": 1.00},
    "ST": {"usability": 0.154, "open_space": 0.30, "net_density": 4.00, "gross_density": 3.00},
    "NC10": {"usability": 0.154, "open_space": 0.30, "net_density": 4.00, "gross_density": 3.00},
    "NC6.5": {"usability": 0.154, "open_space": 0.30, "net_density": 4.00, "gross_density": 3.00},
    "NC5": {"usability": 0.154, "open_space": 0.30, "net_density": 4.00, "gross_density": 3.00},
    "NCSD": {"usability": 0.154, "open_space": 0.30, "net_density": 4.00, "gross_density": 3.00},
    "NCTH": {"usability": 0.154, "open_space": 0.30, "net_density": 4.00, "gross_density": 3.00},
    "NCGA": {"usability": 0.154, "open_space": 0.30, "net_density": 4.00, "gross_density": 3.00},
    "NCAP": {"usability": 0.154, "open_space": 0.30, "net_density": 4.00, "gross_density": 3.00},
    "NCMM": {"usability": 0.136, "open_space": 0.30, "net_density": 4.00, "gross_density": 3.00},
}


COUNTY_NONRESIDENTIAL_FALLBACK_STANDARDS: dict[tuple[str, str], BulkStandard] = {
    ("BP", "office"): BulkStandard("BP", "Offices", 0.20, 0.50, 0.83, "P", "25 ac.", "5 ac.", "Municode Table 40.04.110"),
    ("BP", "industrial"): BulkStandard("BP", "Industrial", 0.30, 0.40, 0.57, "P", "25 ac.", "5 ac.", "Municode Table 40.04.110"),
    ("BP", "commercial"): BulkStandard("BP", "Other permitted uses", 0.30, 0.26, 0.38, "P", "25 ac.", "2 ac.", "Municode Table 40.04.110"),
    ("BP", "mixed_use"): BulkStandard("BP", "Other permitted uses", 0.30, 0.26, 0.38, "P", "25 ac.", "2 ac.", "Municode Table 40.04.110"),
    ("BP", "other_permitted"): BulkStandard("BP", "Other permitted uses", 0.30, 0.26, 0.38, "P", "25 ac.", "2 ac.", "Municode Table 40.04.110"),
    ("BP", "custom"): BulkStandard("BP", "Other permitted uses", 0.30, 0.26, 0.38, "P", "25 ac.", "2 ac.", "Municode Table 40.04.110"),
    ("BP", "solar"): BulkStandard("BP", "Other permitted uses", 0.30, 0.26, 0.38, "P", "25 ac.", "2 ac.", "Municode Table 40.04.110"),
}


USE_TABLE_LABELS: dict[str, str] = {
    "single_family_detached": "Single-family, detached",
    "two_family": "Two-family",
    "townhouse": "Single-family, attached",
    "semi_detached": "Single-family, attached",
    "garden_apartment": "Garden apartments",
    "apartment": "Apartments",
    "commercial_apartment": "Commercial apartments",
    "manufactured_home": "Manufactured home park",
    "office": "Office",
    "commercial_retail": "Commercial retail and service",
    "commercial": "Commercial retail and service",
    "restaurant": "Restaurants",
    "commercial_lodging": "Commercial lodging",
    "heavy_retail": "Heavy retail and service",
    "industrial": "Industrial",
    "mixed_use": "Mixed use",
    "institutional_regional": "Institutional, regional",
    "institutional_neighborhood": "Institutional, neighborhood",
    "institutional_residential": "Institutional, residential (Type I)",
    "hospital": "Hospitals",
    "school": "Schools",
    "college": "Colleges",
    "solar": "Solar energy system, large scale",
    "other_permitted": "Other permitted uses",
    "custom": "Other permitted uses",
}


DEFINITION_TO_USE_KEY: dict[str, str] = {
    "single-family detached": "single_family_detached",
    "single-family attached": "townhouse",
    "multi-family": "apartment",
    "commercial apartment": "commercial_apartment",
    "manufactured home park": "manufactured_home",
    "schools": "school",
    "colleges": "college",
    "institutional, regional": "institutional_regional",
    "institutional, neighborhood": "institutional_neighborhood",
    "institutional, residential": "institutional_residential",
    "commercial lodging": "commercial_lodging",
    "commercial retail and service": "commercial_retail",
    "heavy retail and service": "heavy_retail",
    "mixed use": "mixed_use",
    "restaurants": "restaurant",
    "office": "office",
    "light industry": "industrial",
    "heavy industry": "industrial",
    "solar energy system large scale": "solar",
    "solar energy system": "solar",
}


ADVANCED_USE_ALIASES: dict[str, tuple[str, str]] = {
    "hospital": ("hospital", "Matched hospital to NCC's Hospitals use."),
    "clinic": ("office", "Medical clinic is screened as Office unless the county classifies it as Hospitals or another institutional use."),
    "medical office": ("office", "Medical office is screened as Office."),
    "doctor": ("office", "Medical office is screened as Office."),
    "cigarette": ("commercial_retail", "No cigarette-specific use was found; screened as Commercial retail and service."),
    "tobacco": ("commercial_retail", "No tobacco-specific use was found; screened as Commercial retail and service."),
    "smoke shop": ("commercial_retail", "No smoke-shop-specific use was found; screened as Commercial retail and service."),
    "vape": ("commercial_retail", "No vape-specific use was found; screened as Commercial retail and service."),
    "retail": ("commercial_retail", "Matched retail to Commercial retail and service."),
    "store": ("commercial_retail", "Matched store to Commercial retail and service."),
    "restaurant": ("restaurant", "Matched restaurant to NCC's Restaurants use."),
    "warehouse": ("industrial", "Screened warehouse-like use as Industrial pending county interpretation."),
    "manufacturing": ("industrial", "Screened manufacturing use as Industrial."),
    "school": ("school", "Matched school to NCC's Schools use."),
    "college": ("college", "Matched college to NCC's Colleges use."),
    "church": ("institutional_neighborhood", "Screened place of worship as Institutional, neighborhood unless scale indicates regional institutional use."),
    "worship": ("institutional_neighborhood", "Screened place of worship as Institutional, neighborhood unless scale indicates regional institutional use."),
    "day care": ("institutional_neighborhood", "Screened day care conservatively as Institutional, neighborhood unless home-use standards apply."),
    "office": ("office", "Matched office to NCC's Office use."),
    "mixed use": ("mixed_use", "Matched mixed use to NCC's Mixed use."),
    "apartment": ("apartment", "Matched apartment to NCC's Apartments use."),
    "commercial apartment": ("commercial_apartment", "Matched commercial apartment to NCC's Commercial apartments use."),
    "solar": ("solar", "Screened solar panels as a large-scale solar energy system / utility-style permitted-use candidate pending NCC interpretation."),
    "solar panel": ("solar", "Screened solar panels as a large-scale solar energy system / utility-style permitted-use candidate pending NCC interpretation."),
    "photovoltaic": ("solar", "Screened photovoltaic panels as a large-scale solar energy system / utility-style permitted-use candidate pending NCC interpretation."),
    "renewable": ("solar", "Screened renewable-energy use as a large-scale solar energy system / utility-style permitted-use candidate pending NCC interpretation."),
    "battery storage": ("solar", "Screened battery/energy storage with solar and utility-style uses pending NCC interpretation."),
}


COUNTY_USE_RULES: dict[str, set[str]] = {
    "single_family_detached": {"SR", "SE", "S", "NC5", "NC6.5", "NC10", "NC15", "NC21", "NC40", "NC2A"},
    "two_family": {"NCSD"},
    "townhouse": {"NCTH"},
    "semi_detached": {"NCSD"},
    "garden_apartment": {"NCGA"},
    "apartment": {"NCAP"},
    "manufactured_home": {"NCMM"},
}


DEVELOPMENT_OPTIONS: dict[str, str] = {
    "Single-family detached dwelling": "single_family_detached",
    "Two-family dwelling": "two_family",
    "Townhouse dwelling": "townhouse",
    "Semi-detached dwelling": "semi_detached",
    "Garden apartment": "garden_apartment",
    "Apartment building": "apartment",
    "Commercial apartments": "commercial_apartment",
    "Manufactured/mobile home": "manufactured_home",
    "Office or professional use": "office",
    "Retail or commercial use": "commercial",
    "Industrial use": "industrial",
    "Mixed use development": "mixed_use",
    "Other / custom use": "custom",
}


class ZoningFeasibilityRunner:
    def __init__(
        self,
        parcel_number: str,
        development_option: str = "",
        intended_use: str = "",
        progress: Progress | None = None,
    ) -> None:
        self.parcel_number = parcel_number.strip()
        self.parcel_numbers = split_parcel_inputs(self.parcel_number)
        self.search_parcel_number = parcel_key(self.parcel_numbers[0] if self.parcel_numbers else self.parcel_number)
        self.development_option = development_option.strip()
        self.intended_use = intended_use.strip()
        self.progress = progress or (lambda _message: None)
        self._last_municipal_zoning_coverage: tuple[ZoningCoverage, ...] = ()

    def analyze(self) -> FeasibilityResult:
        self.progress("Finding parcel")
        parcel = self._fetch_parcel()
        self.progress("Checking municipality")
        municipality = self._fetch_municipality(parcel.geometry, parcel.incorporated_hint)
        incorporated = municipality != "Unincorporated New Castle County"
        self.progress("Checking zoning district")
        if incorporated:
            try:
                districts = self._fetch_municipal_zoning(parcel.geometry)
            except RuntimeError:
                self.progress("Municipal zoning layer unavailable; using municipal bot profile")
                districts = ()
        else:
            try:
                districts = self._fetch_county_zoning(parcel.geometry)
            except RuntimeError:
                self.progress("Zoning layer unavailable; review required")
                districts = ()
        if incorporated:
            self.progress("Using municipal bot profile")
            protected_resources: tuple[ProtectedResourceResult, ...] = ()
        elif not districts:
            protected_resources = ()
        else:
            self.progress("Measuring protected resources")
            protected_resources = self._measure_protected_resources(parcel.geometry, tuple(district.code.upper() for district in districts))
        self.progress("Building yield matrix")
        return self._build_result(parcel, municipality, incorporated, districts, protected_resources)

    def write_report(self, result: FeasibilityResult, destination: Path) -> Path:
        destination.mkdir(parents=True, exist_ok=True)
        parcel_file = self._safe_file_part(result.parcel.parcel_number or self.parcel_number)
        path = destination / f"{parcel_file} Zoning Feasibility Report.txt"
        path.write_text(self._report_text(result), encoding="utf-8")
        return path

    def _fetch_parcel(self) -> ParcelRecord:
        if len(self.parcel_numbers) > 1:
            return self._fetch_assembled_parcel()
        if self.parcel_numbers:
            return self._fetch_single_parcel(self.search_parcel_number)
        return self._fetch_single_address(self.parcel_number)

    def _fetch_single_parcel(self, search_parcel_number: str) -> ParcelRecord:
        where = parcel_where(search_parcel_number)
        data = self._fetch_json(
            PARCEL_QUERY_URL,
            {
                "f": "json",
                "where": where,
                "outFields": "PARCELNO,PRCLID,SHORTPRCL,ADDRESS,PROPCITY,PROPSTATE,PROPZIP,CNTCTLAST,INCORP,LOTSZ,LOTFRONTAG,LOTDPTH",
                "returnGeometry": "true",
                "outSR": MAP_SPATIAL_REFERENCE,
            },
        )
        features = data.get("features") or []
        if not features:
            raise RuntimeError(f"Parcel {search_parcel_number} was not found in the county GIS service.")
        return self._parcel_record_from_feature(features[0], search_parcel_number)

    def _fetch_single_address(self, address: str) -> ParcelRecord:
        for where in (address_where(address), fallback_address_where(address)):
            if not where:
                continue
            data = self._fetch_json(
                PARCEL_QUERY_URL,
                {
                    "f": "json",
                    "where": where,
                    "outFields": "PARCELNO,PRCLID,SHORTPRCL,ADDRESS,PROPCITY,PROPSTATE,PROPZIP,CNTCTLAST,INCORP,LOTSZ,LOTFRONTAG,LOTDPTH,PRIMADDR",
                    "returnGeometry": "true",
                    "outSR": MAP_SPATIAL_REFERENCE,
                },
            )
            features = data.get("features") or []
            if features:
                feature = self._preferred_address_feature(features)
                return self._parcel_record_from_feature(feature, address)
        raise RuntimeError(f"Address '{address}' was not found in the county GIS service.")

    def _preferred_address_feature(self, features: list[dict]) -> dict:
        return sorted(features, key=lambda feature: 0 if (feature.get("attributes") or {}).get("PRIMADDR") == "Y" else 1)[0]

    def _parcel_record_from_feature(self, feature: dict, fallback_parcel_number: str) -> ParcelRecord:
        attributes = feature.get("attributes") or {}
        geometry = feature.get("geometry") or {}
        parcel_number = attributes.get("PARCELNO") or attributes.get("PRCLID") or attributes.get("SHORTPRCL") or fallback_parcel_number
        address_parts = (
            self._clean(attributes.get("ADDRESS")),
            self._clean(attributes.get("PROPCITY")),
            self._clean(attributes.get("PROPSTATE")),
            self._clean(attributes.get("PROPZIP")),
        )
        return ParcelRecord(
            parcel_number=str(parcel_number),
            address=", ".join(part for part in address_parts if part),
            owner=self._clean(attributes.get("CNTCTLAST")),
            incorporated_hint=self._clean(attributes.get("INCORP")),
            lot_size=self._as_float(attributes.get("LOTSZ")),
            frontage=self._as_float(attributes.get("LOTFRONTAG")),
            depth=self._as_float(attributes.get("LOTDPTH")),
            geometry=geometry,
        )

    def _fetch_assembled_parcel(self) -> ParcelRecord:
        parcels = [self._fetch_single_parcel(parcel_key(parcel_number)) for parcel_number in self.parcel_numbers]
        geometries = []
        for parcel in parcels:
            geometry = dict(parcel.geometry)
            if geometry.get("rings"):
                geometry["spatialReference"] = {"wkid": int(MAP_SPATIAL_REFERENCE)}
                geometries.append(geometry)
        unioned = self._union_geometries(geometries)
        if not unioned:
            raise RuntimeError("The selected parcels were found, but their combined geometry could not be built.")

        owners = tuple(dict.fromkeys(parcel.owner for parcel in parcels if parcel.owner))
        incorporations = tuple(dict.fromkeys(parcel.incorporated_hint for parcel in parcels if parcel.incorporated_hint))
        addresses = tuple(dict.fromkeys(parcel.address for parcel in parcels if parcel.address))
        frontage_values = [parcel.frontage for parcel in parcels if parcel.frontage is not None]
        depth_values = [parcel.depth for parcel in parcels if parcel.depth is not None]
        lot_size_values = [parcel.lot_size for parcel in parcels if parcel.lot_size is not None]
        parcel_label = " + ".join(parcel.parcel_number for parcel in parcels)
        return ParcelRecord(
            parcel_number=parcel_label,
            address=f"{len(parcels)}-parcel assembled site" if len(addresses) != 1 else addresses[0],
            owner=owners[0] if len(owners) == 1 else "Multiple owners",
            incorporated_hint=incorporations[0] if len(incorporations) == 1 else "",
            lot_size=sum(lot_size_values) if lot_size_values else None,
            frontage=sum(frontage_values) if frontage_values else None,
            depth=max(depth_values) if depth_values else None,
            geometry=unioned,
        )

    def _fetch_municipality(self, parcel_geometry: dict, incorporated_hint: str) -> str:
        data = self._fetch_json(
            MUNICIPALITY_QUERY_URL,
            {
                "f": "json",
                "where": "1=1",
                "outFields": "NAME",
                "returnGeometry": "false",
                "geometry": json.dumps(parcel_geometry, separators=(",", ":")),
                "geometryType": "esriGeometryPolygon",
                "inSR": MAP_SPATIAL_REFERENCE,
                "spatialRel": "esriSpatialRelIntersects",
            },
        )
        names = [self._clean((feature.get("attributes") or {}).get("NAME")) for feature in data.get("features") or []]
        names = [name for name in names if name]
        if names:
            return ", ".join(sorted(set(names)))
        if incorporated_hint and not self._is_unincorporated_hint(incorporated_hint):
            return incorporated_hint
        return "Unincorporated New Castle County"

    def _fetch_county_zoning(self, parcel_geometry: dict) -> tuple[ZoningDistrict, ...]:
        try:
            data = self._query_by_geometry(COUNTY_ZONING_QUERY_URL, parcel_geometry, "CODE,DESCRIPTION,GENERIC_DESCRIPTION")
        except RuntimeError:
            try:
                data = self._query_by_point(COUNTY_ZONING_QUERY_URL, parcel_geometry, "CODE,DESCRIPTION,GENERIC_DESCRIPTION")
            except RuntimeError:
                return self._fetch_county_zoning_from_sublayers(parcel_geometry)
        if not data.get("features"):
            try:
                data = self._query_by_point(COUNTY_ZONING_QUERY_URL, parcel_geometry, "CODE,DESCRIPTION,GENERIC_DESCRIPTION")
            except RuntimeError:
                return self._fetch_county_zoning_from_sublayers(parcel_geometry)
        districts: list[ZoningDistrict] = []
        for feature in data.get("features") or []:
            attributes = feature.get("attributes") or {}
            code = self._clean(attributes.get("CODE")).upper()
            if not code:
                continue
            description = self._clean(attributes.get("DESCRIPTION")) or self._clean(attributes.get("GENERIC_DESCRIPTION"))
            districts.append(ZoningDistrict(code=code, description=description, source_url=self._county_zoning_url(code)))
        deduped = self._dedupe_districts(districts)
        return deduped or self._fetch_county_zoning_from_sublayers(parcel_geometry)

    def _fetch_county_zoning_from_sublayers(self, parcel_geometry: dict) -> tuple[ZoningDistrict, ...]:
        districts: list[ZoningDistrict] = []
        for layer_id in COUNTY_ZONING_FALLBACK_LAYER_IDS:
            url = f"{NCC_ZONING_MAPSERVER_URL}/{layer_id}/query"
            try:
                data = self._query_by_geometry(url, parcel_geometry, "CODE,DESCRIPTION,GENERIC_DESCRIPTION")
            except RuntimeError:
                try:
                    data = self._query_by_point(url, parcel_geometry, "CODE,DESCRIPTION,GENERIC_DESCRIPTION")
                except RuntimeError:
                    continue
            if not data.get("features"):
                try:
                    data = self._query_by_point(url, parcel_geometry, "CODE,DESCRIPTION,GENERIC_DESCRIPTION")
                except RuntimeError:
                    continue
            for feature in data.get("features") or []:
                attributes = feature.get("attributes") or {}
                code = self._clean(attributes.get("CODE")).upper()
                if not code:
                    continue
                description = self._clean(attributes.get("DESCRIPTION")) or self._clean(attributes.get("GENERIC_DESCRIPTION"))
                districts.append(ZoningDistrict(code=code, description=description, source_url=self._county_zoning_url(code)))
        return self._dedupe_districts(districts)

    def _fetch_municipal_zoning(self, parcel_geometry: dict) -> tuple[ZoningDistrict, ...]:
        parcel_area_acres = max(self._polygon_area(parcel_geometry) / ACRE_SF, 0.0)
        try:
            data = self._fetch_json(
                MUNICIPAL_ZONING_QUERY_URL,
                {
                    "f": "json",
                    "where": "1=1",
                    "outFields": "*",
                    "returnGeometry": "true",
                    "outSR": MAP_SPATIAL_REFERENCE,
                    "geometry": json.dumps(parcel_geometry, separators=(",", ":")),
                    "geometryType": "esriGeometryPolygon",
                    "inSR": MAP_SPATIAL_REFERENCE,
                    "spatialRel": "esriSpatialRelIntersects",
                },
            )
        except RuntimeError:
            return self._fetch_municipal_zoning_by_point(parcel_geometry)
        districts: list[ZoningDistrict] = []
        coverage: list[ZoningCoverage] = []
        for feature in data.get("features") or []:
            attributes = feature.get("attributes") or {}
            code = normalize_municipal_zoning_code(self._clean(self._first_attr(attributes, ("ZONE", "GIS_ADM.TownZoning_Polys.ZONE"))))
            if not code:
                continue
            description = district_label(
                code,
                self._clean(self._first_attr(attributes, ("ZONE_DESC", "GIS_ADM.TownZoning_Polys.ZONE_DESC"))),
            )
            source_url = self._clean(self._first_attr(attributes, ("URL", "GIS_ADM.Townzoning_URLs.URL")))
            map_url = self._clean(self._first_attr(attributes, ("URL2", "GIS_ADM.Townzoning_URLs.URL2")))
            district = ZoningDistrict(code=code, description=description, source_url=source_url, map_url=map_url)
            districts.append(district)
            acres = self._municipal_zoning_area_acres(parcel_geometry, feature.get("geometry") or {})
            percent = acres / parcel_area_acres if parcel_area_acres > 0 else 0.0
            if acres > 0.0001:
                coverage.append(ZoningCoverage(district=district, acres=acres, percent=percent))
        deduped = self._dedupe_districts(districts)
        self._last_municipal_zoning_coverage = tuple(
            sorted(
                self._dedupe_coverage(coverage),
                key=lambda item: item.acres,
                reverse=True,
            )
        )
        if not deduped:
            return self._fetch_municipal_zoning_by_point(parcel_geometry)
        return deduped

    def _fetch_municipal_zoning_by_point(self, parcel_geometry: dict) -> tuple[ZoningDistrict, ...]:
        data = self._query_by_point(MUNICIPAL_ZONING_QUERY_URL, parcel_geometry, "*")
        districts: list[ZoningDistrict] = []
        for feature in data.get("features") or []:
            attributes = feature.get("attributes") or {}
            code = normalize_municipal_zoning_code(self._clean(self._first_attr(attributes, ("ZONE", "GIS_ADM.TownZoning_Polys.ZONE"))))
            if not code:
                continue
            description = district_label(
                code,
                self._clean(self._first_attr(attributes, ("ZONE_DESC", "GIS_ADM.TownZoning_Polys.ZONE_DESC"))),
            )
            source_url = self._clean(self._first_attr(attributes, ("URL", "GIS_ADM.Townzoning_URLs.URL")))
            map_url = self._clean(self._first_attr(attributes, ("URL2", "GIS_ADM.Townzoning_URLs.URL2")))
            districts.append(ZoningDistrict(code=code, description=description, source_url=source_url, map_url=map_url))
        self._last_municipal_zoning_coverage = ()
        return self._dedupe_districts(districts)

    def _municipal_zoning_area_acres(self, parcel_geometry: dict, zoning_geometry: dict) -> float:
        if not zoning_geometry.get("rings"):
            return 0.0
        parcel = dict(parcel_geometry)
        parcel["spatialReference"] = {"wkid": int(MAP_SPATIAL_REFERENCE)}
        zoning = dict(zoning_geometry)
        zoning["spatialReference"] = {"wkid": int(MAP_SPATIAL_REFERENCE)}
        try:
            intersected = self._fetch_json(
                GEOMETRY_INTERSECT_URL,
                {
                    "f": "json",
                    "sr": MAP_SPATIAL_REFERENCE,
                    "geometry": json.dumps({"geometryType": "esriGeometryPolygon", "geometry": parcel}, separators=(",", ":")),
                    "geometries": json.dumps({"geometryType": "esriGeometryPolygon", "geometries": [zoning]}, separators=(",", ":")),
                },
            )
            geometries = [geometry for geometry in (intersected.get("geometries") or []) if geometry.get("rings")]
            return self._geometry_area_acres(geometries)
        except RuntimeError:
            return 0.0

    def _dedupe_coverage(self, coverage: list[ZoningCoverage]) -> tuple[ZoningCoverage, ...]:
        by_code: dict[str, ZoningCoverage] = {}
        for item in coverage:
            key = item.district.code.upper()
            previous = by_code.get(key)
            if previous is None:
                by_code[key] = item
            else:
                total_acres = previous.acres + item.acres
                by_code[key] = ZoningCoverage(
                    district=previous.district,
                    acres=total_acres,
                    percent=previous.percent + item.percent,
                )
        return tuple(by_code.values())

    def _build_result(
        self,
        parcel: ParcelRecord,
        municipality: str,
        incorporated: bool,
        districts: tuple[ZoningDistrict, ...],
        protected_resources: tuple[ProtectedResourceResult, ...],
    ) -> FeasibilityResult:
        area = self._polygon_area(parcel.geometry)
        efficiency = self._shape_efficiency(parcel.geometry)
        if not districts and not incorporated:
            return FeasibilityResult(
                status="Review Required",
                confidence="Low",
                summary="No zoning district was returned by the GIS zoning layers.",
                details=("Confirm the parcel zoning manually before relying on this result.",),
                standards=(),
                sources=(COUNTY_CODE_HOME,),
                parcel=parcel,
                municipality=municipality,
                zoning_districts=districts,
                parcel_area_sf=area,
                shape_efficiency=efficiency,
                recommendations=(),
                protected_resources=protected_resources,
            )

        if incorporated:
            return self._municipal_result(parcel, municipality, districts, protected_resources)
        return self._county_result(parcel, municipality, districts, protected_resources)

    def _municipal_result(
        self,
        parcel: ParcelRecord,
        municipality: str,
        districts: tuple[ZoningDistrict, ...],
        protected_resources: tuple[ProtectedResourceResult, ...],
    ) -> FeasibilityResult:
        return self._municipal_bot_result(parcel, municipality, districts, protected_resources)

    def _municipal_bot_result(
        self,
        parcel: ParcelRecord,
        municipality: str,
        districts: tuple[ZoningDistrict, ...],
        protected_resources: tuple[ProtectedResourceResult, ...],
    ) -> FeasibilityResult:
        area = self._polygon_area(parcel.geometry)
        efficiency = self._shape_efficiency(parcel.geometry)
        zoning_lines = self._municipal_zoning_lines(districts)
        profile = build_municipal_profile(
            municipality=municipality,
            parcel_area_acres=area / ACRE_SF,
            zoning_lines=zoning_lines,
            resource_warnings=self._resource_warnings(protected_resources),
            parcel_count=max(1, len(self.parcel_numbers)),
        )
        return FeasibilityResult(
            status=profile.status,
            confidence=profile.confidence,
            summary=profile.summary,
            details=profile.details,
            standards=(*self._parcel_standards(parcel, area, efficiency), *profile.standards),
            sources=profile.sources,
            parcel=parcel,
            municipality=municipality,
            zoning_districts=districts,
            parcel_area_sf=area,
            shape_efficiency=efficiency,
            recommendations=tuple(
                YieldRecommendation(
                    development_option=item.development_option,
                    status=item.status,
                    conservative_yield=item.conservative_yield,
                    gross_area_yield=item.gross_area_yield,
                    limiting_factors=item.limiting_factors,
                    note=item.note,
                    market_value_low=item.market_value_low,
                    market_value_high=item.market_value_high,
                    market_basis=item.market_basis,
                )
                for item in profile.recommendations
            ),
            protected_resources=protected_resources,
        )

    def _municipal_zoning_lines(self, districts: tuple[ZoningDistrict, ...]) -> tuple[str, ...]:
        if self._last_municipal_zoning_coverage:
            covered_codes = {item.district.code.upper() for item in self._last_municipal_zoning_coverage}
            lines = [
                f"Municipal zoning overlap: {item.district.code} ({item.district.description or 'unlabeled'}) covers {item.acres:,.3f} ac ({item.percent:.1%} of parcel)."
                for item in self._last_municipal_zoning_coverage
            ]
            lines.extend(
                f"Municipal zoning non-bounded contact: {district.code} ({district.description or 'unlabeled'}) was returned by the GIS intersection but did not produce measurable parcel area above tolerance."
                for district in districts
                if district.code.upper() not in covered_codes
            )
            return tuple(lines)
        return tuple(
            f"Municipal zoning district: {district.code} ({district.description or 'unlabeled'})."
            for district in districts
        )

    def _county_result(
        self,
        parcel: ParcelRecord,
        municipality: str,
        districts: tuple[ZoningDistrict, ...],
        protected_resources: tuple[ProtectedResourceResult, ...],
    ) -> FeasibilityResult:
        codes = tuple(district.code.upper() for district in districts)
        split = len(set(codes)) > 1
        area = self._polygon_area(parcel.geometry)
        efficiency = self._shape_efficiency(parcel.geometry)
        details: list[str] = [
            f"Jurisdiction: {municipality}",
            "New Castle County Code on Municode is the primary ordinance source for unincorporated parcels.",
            "Yield follows the workbook-style protected land and capacity calculation matrix.",
        ]
        if len(self.parcel_numbers) > 1:
            details.append(
                f"Assembled-site screen: {len(self.parcel_numbers)} parcel geometries were combined before zoning, resource, and yield calculations."
            )
        details.extend(self._resource_warnings(protected_resources))
        standards = list(self._parcel_standards(parcel, area, efficiency))
        standards.extend(self._protected_resource_lines(protected_resources))

        if split:
            details.append(
                "Split zoning is present. PropSpector screens two rezoning assumptions: one applying the lowest-return mapped district to the whole parcel, and one applying the highest-return mapped district to the whole parcel."
            )

        capacity_matrix = self._capacity_matrix_for_codes(codes, area, protected_resources)
        recommendations = (
            self._split_zoning_scenario_recommendations(parcel, codes, area, efficiency, protected_resources)
            if split
            else self._county_recommendations(parcel, codes, area, efficiency, capacity_matrix, protected_resources)
        )
        top_recommendation = recommendations[0] if recommendations else None
        permitted = [item for item in recommendations if item.status == "By Right"]
        review = [item for item in recommendations if "Review" in item.status]
        if top_recommendation and top_recommendation.conservative_yield:
            status = "Yield Screening Complete"
            confidence = "Medium"
            value = self._money_range(top_recommendation.market_value_low, top_recommendation.market_value_high) if top_recommendation.market_value_low is not None and top_recommendation.market_value_high is not None else "no value screen"
            if top_recommendation.program_scenario:
                scenario = top_recommendation.program_scenario
                summary = (
                    f"Top ranked option: {top_recommendation.development_option} with "
                    f"{scenario.modeled_units or 0:,} apartment units modeled within an approximately "
                    f"{scenario.envelope_gfa or 0:,} sf GFA envelope; {value} value screen."
                )
            else:
                summary = (
                    f"Top ranked option: {top_recommendation.development_option} at "
                    f"{top_recommendation.conservative_yield:,} planning-level yield; {value} value screen."
                )
        elif review:
            status = "Use Table Review Required"
            confidence = "Medium"
            summary = "No encoded by-right residential yield was found; one or more options require manual use-table confirmation."
        else:
            status = "Variance or Rezoning Likely"
            confidence = "Medium"
            summary = "The encoded development options do not appear by-right in the mapped county zoning district."

        sources = tuple(dict.fromkeys(url for district in districts for url in (COUNTY_CODE_HOME, district.source_url) if url))
        return FeasibilityResult(
            status=status,
            confidence=confidence,
            summary=summary,
            details=tuple(details),
            standards=tuple(standards),
            sources=sources or (COUNTY_CODE_HOME,),
            parcel=parcel,
            municipality=municipality,
            zoning_districts=districts,
            parcel_area_sf=area,
            shape_efficiency=efficiency,
            recommendations=tuple(recommendations),
            protected_resources=protected_resources,
            capacity_matrix=capacity_matrix,
        )

    def _split_zoning_scenario_recommendations(
        self,
        parcel: ParcelRecord,
        codes: tuple[str, ...],
        parcel_area: float,
        shape_efficiency: float,
        fallback_resources: tuple[ProtectedResourceResult, ...],
    ) -> list[YieldRecommendation]:
        scenarios: list[tuple[str, list[YieldRecommendation], tuple[ProtectedResourceResult, ...]]] = []
        for code in sorted(set(codes)):
            try:
                resources = self._measure_protected_resources(parcel.geometry, (code,))
            except RuntimeError:
                resources = fallback_resources
            matrix = self._capacity_matrix_for_codes((code,), parcel_area, resources)
            recommendations = self._county_recommendations(parcel, (code,), parcel_area, shape_efficiency, matrix, resources)
            if recommendations:
                scenarios.append((code, recommendations, resources))
        if not scenarios:
            return self._county_recommendations(parcel, codes, parcel_area, shape_efficiency, None, fallback_resources)

        def top_rank(item: tuple[str, list[YieldRecommendation], tuple[ProtectedResourceResult, ...]]) -> tuple[int, float, int]:
            return self._recommendation_rank_key(item[1][0])

        restrictive = min(scenarios, key=top_rank)
        lucrative = max(scenarios, key=top_rank)
        selected: list[tuple[str, str, list[YieldRecommendation]]] = [
            ("Restrictive Rezoning", restrictive[0], restrictive[1]),
        ]
        if lucrative[0] != restrictive[0]:
            selected.append(("Upside Rezoning", lucrative[0], lucrative[1]))

        scenario_recommendations: list[YieldRecommendation] = []
        for scenario_name, code, recommendations in selected:
            for recommendation in recommendations:
                if recommendation.status == "Not By Right" and not recommendation.conservative_yield:
                    continue
                note = (
                    f"{scenario_name} assumption: the entire parcel is screened as {code}. "
                    f"{recommendation.note}"
                ).strip()
                scenario_recommendations.append(
                    replace(
                        recommendation,
                        development_option=f"{scenario_name} ({code}) - {recommendation.development_option}",
                        note=note,
                    )
                )
        return self._ranked_recommendations(scenario_recommendations, parcel)

    def _county_recommendations(
        self,
        parcel: ParcelRecord,
        codes: tuple[str, ...],
        parcel_area: float,
        shape_efficiency: float,
        capacity_matrix: CapacityMatrix | None,
        protected_resources: tuple[ProtectedResourceResult, ...],
    ) -> list[YieldRecommendation]:
        recommendations: list[YieldRecommendation] = []
        for option, use_key in DEVELOPMENT_OPTIONS.items():
            permission = self._use_permission(codes, use_key)
            if permission == "N":
                recommendations.append(
                    YieldRecommendation(
                        development_option=option,
                        status="Not By Right",
                        conservative_yield=0,
                        gross_area_yield=0,
                        limiting_factors=("Municode use table",),
                        note="Municode Sec. 40.03.110 use table lists this use as not permitted in the mapped zoning district.",
                    )
                )
                continue
            if use_key == "commercial_apartment":
                units, caveat = self._commercial_apartment_unit_screen(codes, parcel_area, protected_resources)
                recommendations.append(
                    YieldRecommendation(
                        development_option=option,
                        status=self._permission_status(permission, units > 0),
                        conservative_yield=units if units > 0 else None,
                        gross_area_yield=None,
                        limiting_factors=("Section 40.03.305 limited-use standards", "500 sf outdoor area per unit", "building program required"),
                        note=caveat,
                    )
                )
                continue
            nonres_standard = self._nonresidential_bulk_standard(codes, use_key)
            if nonres_standard:
                matrix = self._nonresidential_capacity_matrix(parcel_area, protected_resources, nonres_standard, use_key)
                floor_area = matrix.maximum_floor_area_sf if matrix else 0
                status = self._permission_status(permission, floor_area > 0)
                note = (
                    f"Uses Municode Table 40.04.110 {nonres_standard.zoning_code} {nonres_standard.use_label}: "
                    f"landscape {nonres_standard.minimum_landscape_ratio:.2f}, gross FAR {nonres_standard.maximum_gross_far:.2f}, "
                    f"net FAR {nonres_standard.maximum_net_far:.2f}."
                )
                program_scenario = None
                if use_key == "mixed_use":
                    apartment_units = self._mixed_use_apartment_units(codes, parcel, parcel_area, shape_efficiency, protected_resources)
                    mixed_commercial_gfa = math.floor(math.floor(floor_area * MIXED_USE_PROGRAM_GFA_UTILIZATION) * MIXED_USE_COMMERCIAL_GFA_SHARE)
                    site_units = self._site_supported_apartment_units(parcel_area, matrix, mixed_commercial_gfa)
                    program_scenario = self._mixed_use_program_scenario(
                        envelope_gfa=matrix.district_floor_area_sf if matrix else floor_area,
                        program_gfa=floor_area,
                        apartment_units=apartment_units,
                        site_units=site_units,
                        default_commercial_gfa=mixed_commercial_gfa,
                    )
                    note = (
                        f"{note} Mixed-use screen: theoretical envelope {program_scenario.envelope_gfa or 0:,} sf GFA; "
                        f"derived residential unit screen {program_scenario.modeled_units or 0:,} apartment units within that envelope; "
                        f"code-derived program allocation {program_scenario.total_program_gfa or 0:,} sf total GFA "
                        f"({program_scenario.residential_gfa or 0:,} residential, "
                        f"{program_scenario.commercial_gfa or 0:,} retail/commercial, "
                        f"{program_scenario.accessory_gfa or 0:,} clubhouse/maintenance/accessory). "
                        f"{program_scenario.caveat} {YIELD_PLANNING_DISCLAIMER}"
                    ).strip()
                recommendations.append(
                    YieldRecommendation(
                        development_option=option,
                        status=status,
                        conservative_yield=floor_area,
                        gross_area_yield=matrix.district_floor_area_sf if matrix else None,
                        limiting_factors=self._nonresidential_limiting_factors(matrix),
                        note=note,
                        program_scenario=program_scenario,
                    )
                )
                continue
            allowed_codes = COUNTY_USE_RULES.get(use_key)
            if allowed_codes is None:
                recommendations.append(
                    YieldRecommendation(
                        development_option=option,
                        status="Review Required",
                        conservative_yield=None,
                        gross_area_yield=None,
                        limiting_factors=("Use table not encoded yet",),
                        note="Confirm permitted use, special use, and bulk standards in Municode.",
                    )
                )
                continue
            if permission in {"L", "S"}:
                recommendations.append(
                    YieldRecommendation(
                        development_option=option,
                        status=self._permission_status(permission, False),
                        conservative_yield=None,
                        gross_area_yield=None,
                        limiting_factors=("Municode use table",),
                        note="Use is not by-right; yield should be treated as entitlement-dependent.",
                    )
                )
                continue
            if permission == "" and not all(code in allowed_codes for code in codes):
                recommendations.append(
                    YieldRecommendation(
                        development_option=option,
                        status="Not By Right",
                        conservative_yield=0,
                        gross_area_yield=0,
                        limiting_factors=("Mapped zoning district",),
                        note="This option does not match the encoded by-right county district family.",
                    )
                )
                continue

            district_yields = [self._yield_for_code(parcel, code, parcel_area, shape_efficiency, capacity_matrix) for code in codes]
            conservative_yield = min(item.conservative_yield or 0 for item in district_yields)
            gross_yield = min(item.gross_area_yield or 0 for item in district_yields)
            limiting = tuple(dict.fromkeys(factor for item in district_yields for factor in item.limiting_factors))
            recommendations.append(
                YieldRecommendation(
                    development_option=option,
                    status="By Right" if conservative_yield > 0 else "Dimensional Variance Likely",
                    conservative_yield=conservative_yield,
                    gross_area_yield=gross_yield,
                    limiting_factors=limiting,
                    note=(
                        "Conservative yield assumes legal lot layout must survive frontage, access, shape constraints, "
                        "off-street parking, driveways, fire access, stormwater, and subdivision design."
                    ),
                )
            )
        advanced = self._advanced_use_recommendation(parcel, codes, parcel_area, shape_efficiency, protected_resources)
        if advanced:
            recommendations.insert(0, advanced)
        return self._ranked_recommendations(recommendations, parcel)

    def _ranked_recommendations(self, recommendations: list[YieldRecommendation], parcel: ParcelRecord) -> list[YieldRecommendation]:
        screened = [self._with_private_market_context(self._with_market_screen(item), parcel) for item in recommendations]
        return sorted(screened, key=self._recommendation_rank_key, reverse=True)

    def _with_market_screen(self, recommendation: YieldRecommendation) -> YieldRecommendation:
        low, high, basis = self._market_screen(recommendation)
        if low is None or high is None or not basis:
            return recommendation
        note = recommendation.note
        market_note = f"Planning value screen: {self._money_range(low, high)}; {basis}."
        if market_note not in note:
            note = f"{note} {market_note}".strip()
        return replace(recommendation, note=note, market_value_low=low, market_value_high=high, market_basis=basis)

    def _recommendation_rank_key(self, recommendation: YieldRecommendation) -> tuple[int, float, int]:
        status_rank = {
            "By Right": 60,
            "Limited Use Review": 50,
            "Special Use Review": 40,
            "Interpretation Required": 30,
            "Review Required": 20,
            "Dimensional Variance Likely": 10,
            "Not By Right": 0,
        }.get(recommendation.status, 0)
        low = recommendation.market_value_low or 0
        high = recommendation.market_value_high or 0
        midpoint = (low + high) / 2
        return int(midpoint), status_rank, recommendation.conservative_yield or 0

    def _with_private_market_context(self, recommendation: YieldRecommendation, parcel: ParcelRecord) -> YieldRecommendation:
        if not self._is_public_owner(parcel.owner) or not self._is_civic_other_bucket(recommendation):
            return recommendation
        base_note = re.sub(r"\s*Planning value screen:.*$", "", recommendation.note).strip()
        note = (
            f"{base_note} Private-market ranking note: owner appears public or quasi-public "
            f"({parcel.owner}); institutional/civic/other permitted-use GFA is ranked below ordinary private-development options."
        ).strip()
        return replace(
            recommendation,
            note=note,
            market_value_low=0,
            market_value_high=0,
            market_basis="public-owner civic/institutional use; not treated as a private-development opportunity",
        )

    def _is_civic_other_bucket(self, recommendation: YieldRecommendation) -> bool:
        option = recommendation.development_option.lower()
        return (
            "other / custom" in option
            or "institutional" in option
            or "civic" in option
            or "utility" in option
            or "solar" in option
        )

    def _is_public_owner(self, owner: str) -> bool:
        clean = owner.upper()
        public_terms = (
            "STATE OF",
            "COUNTY",
            "CITY OF",
            "TOWN OF",
            "SCHOOL DISTRICT",
            "BOARD OF EDUCATION",
            "DEPARTMENT",
            "AUTHORITY",
            "UNIVERSITY OF",
            "UNITED STATES",
            "U S OF AMERICA",
            "US OF AMERICA",
            "FEDERAL",
        )
        return any(term in clean for term in public_terms)

    def _mixed_use_program_scenario(
        self,
        envelope_gfa: int,
        program_gfa: int,
        apartment_units: int,
        site_units: int,
        default_commercial_gfa: int,
    ) -> ProgramScenario:
        total_program = math.floor(program_gfa * MIXED_USE_PROGRAM_GFA_UTILIZATION)
        commercial_gfa = min(default_commercial_gfa, total_program)
        accessory_gfa = 0
        residential_gfa = max(0, total_program - commercial_gfa - accessory_gfa)
        gfa_units = max(0, math.floor(residential_gfa / self._average_gross_unit_area()))
        unit_candidates = [value for value in (apartment_units, site_units, gfa_units) if value > 0]
        modeled_units = min(unit_candidates) if unit_candidates else 0
        total_program_gfa = residential_gfa + commercial_gfa + accessory_gfa
        caveat = (
            "Program GFA exceeds the theoretical envelope; verify the input zoning district, FAR, density, parking, conservancy, and final engineering constraints."
            if envelope_gfa and total_program_gfa > envelope_gfa
            else "Code-derived screen; verify against recorded plans, approvals, conservancy, parking, stormwater, agency review, and final engineering."
        )
        return ProgramScenario(
            title="Code-Derived Mixed-Use Program",
            modeled_units=modeled_units,
            envelope_gfa=envelope_gfa,
            residential_gfa=residential_gfa,
            commercial_gfa=commercial_gfa,
            accessory_gfa=accessory_gfa,
            total_program_gfa=total_program_gfa,
            caveat=caveat,
        )
    def _market_screen(self, recommendation: YieldRecommendation) -> tuple[int | None, int | None, str]:
        if recommendation.conservative_yield is None or recommendation.conservative_yield <= 0:
            return None, None, ""
        option = recommendation.development_option.lower()
        if recommendation.status == "Not By Right":
            return None, None, ""
        if "mixed use" in option:
            commercial_gfa, units = self._mixed_use_split(recommendation)
            gfa_low, gfa_high = self._gfa_income_range(commercial_gfa, option)
            unit_low, unit_high = self._unit_income_range(units)
            return (
                gfa_low + unit_low,
                gfa_high + unit_high,
                f"annual gross income proxy from {commercial_gfa:,} sf commercial GFA and {units:,} apartments within the same mixed-use GFA cap",
            )
        if "apartment" in option or "manufactured" in option or "mobile" in option:
            low, high = self._unit_income_range(recommendation.conservative_yield)
            return low, high, f"annual gross residential income proxy from {recommendation.conservative_yield:,} units"
        if "solar" in option or "utility" in option:
            return None, None, ""
        lot_labels = ("single-family", "two-family", "townhouse", "semi-detached")
        if any(label in option for label in lot_labels):
            low = recommendation.conservative_yield * 90000
            high = recommendation.conservative_yield * 180000
            return low, high, f"lot sale value proxy from {recommendation.conservative_yield:,} lots"
        low, high = self._gfa_income_range(recommendation.conservative_yield, option)
        return low, high, f"annual gross income proxy from {recommendation.conservative_yield:,} sf GFA"

    def _gfa_income_range(self, floor_area_sf: int, option: str) -> tuple[int, int]:
        low_rate, high_rate, _label = self._commercial_rate_range(option)
        return floor_area_sf * low_rate, floor_area_sf * high_rate

    def _commercial_rate_range(self, option: str) -> tuple[int, int, str]:
        if "industrial" in option:
            return COMMERCIAL_RENT_RANGES["industrial"]
        elif "restaurant" in option or "retail" in option or "commercial" in option:
            return COMMERCIAL_RENT_RANGES["commercial"]
        elif "lodging" in option:
            return COMMERCIAL_RENT_RANGES["lodging"]
        return COMMERCIAL_RENT_RANGES["office"]

    def _unit_income_range(self, units: int) -> tuple[int, int]:
        low_monthly = sum(share * low for _bedroom, share, low, _high in APARTMENT_RENT_MIX)
        high_monthly = sum(share * high for _bedroom, share, _low, high in APARTMENT_RENT_MIX)
        return math.floor(units * low_monthly * 12), math.floor(units * high_monthly * 12)

    def _mixed_use_split(self, recommendation: YieldRecommendation) -> tuple[int, int]:
        if recommendation.program_scenario:
            return recommendation.program_scenario.commercial_gfa or 0, recommendation.program_scenario.modeled_units or 0
        site_supported_units = self._mixed_use_site_units_from_note(recommendation.note)
        outdoor_supported_units = self._mixed_use_units_from_note(recommendation.note)
        allowed_gfa = recommendation.conservative_yield or 0
        program_gfa = math.floor(allowed_gfa * MIXED_USE_PROGRAM_GFA_UTILIZATION)
        commercial_gfa = math.floor(program_gfa * MIXED_USE_COMMERCIAL_GFA_SHARE)
        residential_gfa = max(0, program_gfa - commercial_gfa)
        gfa_supported_units = math.floor(residential_gfa / self._average_gross_unit_area())
        unit_candidates = [gfa_supported_units]
        if site_supported_units:
            unit_candidates.append(site_supported_units)
        if outdoor_supported_units:
            unit_candidates.append(outdoor_supported_units)
        units = min(unit_candidates)
        return commercial_gfa, units

    def _average_gross_unit_area(self) -> float:
        average_net_area = sum(share * area for _bedroom, share, area in APARTMENT_UNIT_SIZE_MIX)
        return average_net_area / MIXED_USE_RESIDENTIAL_GROSS_EFFICIENCY

    def _mixed_use_units_from_note(self, note: str) -> int:
        match = re.search(r"residential unit support ([\d,]+)", note)
        if not match:
            return 0
        return int(match.group(1).replace(",", ""))

    def _mixed_use_site_units_from_note(self, note: str) -> int:
        match = re.search(r"site support ([\d,]+)", note)
        if not match:
            return 0
        return int(match.group(1).replace(",", ""))

    def _money_range(self, low: int, high: int) -> str:
        if low == high:
            return self._money(low)
        return f"{self._money(low)}-{self._money(high)}"

    def _money(self, value: int) -> str:
        if value >= 1_000_000:
            return f"${value / 1_000_000:.1f}M"
        if value >= 1_000:
            return f"${value / 1_000:.0f}k"
        return f"${value:,}"

    def _advanced_use_recommendation(
        self,
        parcel: ParcelRecord,
        codes: tuple[str, ...],
        parcel_area: float,
        shape_efficiency: float,
        protected_resources: tuple[ProtectedResourceResult, ...],
    ) -> YieldRecommendation | None:
        if not self.intended_use:
            return None
        classification = self._classify_intended_use(self.intended_use)
        permission = self._use_permission_for_label(codes, classification.official_use)
        title = f"Advanced: {classification.official_use}"
        note_prefix = (
            f"Intended use '{classification.requested_use}' classified as '{classification.official_use}' "
            f"using Municode Division 40.33.200 use definitions. Confidence: {classification.confidence}. "
            f"{classification.rationale}"
        )
        if permission == "N":
            return YieldRecommendation(
                development_option=title,
                status="Not By Right",
                conservative_yield=0,
                gross_area_yield=0,
                limiting_factors=("Municode Sec. 40.03.110 use table",),
                note=f"{note_prefix} The use table lists this use as not permitted in the mapped zoning district.",
            )
        if classification.use_key == "commercial_apartment":
            units, caveat = self._commercial_apartment_unit_screen(codes, parcel_area, protected_resources)
            return YieldRecommendation(
                development_option=title,
                status=self._permission_status(permission, units > 0),
                conservative_yield=units if units > 0 else None,
                gross_area_yield=None,
                limiting_factors=("Section 40.03.305 limited-use standards", "500 sf outdoor area per unit", "building program required"),
                note=f"{note_prefix} {caveat}",
            )
        nonres_standard = self._nonresidential_bulk_standard(codes, classification.use_key)
        if nonres_standard:
            matrix = self._nonresidential_capacity_matrix(parcel_area, protected_resources, nonres_standard, classification.use_key)
            is_solar = classification.use_key == "solar"
            yield_value = math.floor(matrix.net_buildable_site_area_ac * ACRE_SF) if is_solar and matrix else matrix.maximum_floor_area_sf if matrix else 0
            status = "Interpretation Required" if permission == "" else self._permission_status(permission, yield_value > 0)
            yield_note = (
                f"Yield reports {yield_value:,} sf of usable solar/utility site area after mapped protected-resource and landscaped-surface reservations."
                if is_solar
                else (
                    f"Yield uses Municode Table 40.04.110 {nonres_standard.zoning_code} "
                    f"{nonres_standard.use_label}: landscape {nonres_standard.minimum_landscape_ratio:.2f}, "
                    f"gross FAR {nonres_standard.maximum_gross_far:.2f}, net FAR {nonres_standard.maximum_net_far:.2f}."
                )
            )
            return YieldRecommendation(
                development_option=title,
                status=status,
                conservative_yield=yield_value,
                gross_area_yield=matrix.district_floor_area_sf if matrix else None,
                limiting_factors=self._nonresidential_limiting_factors(matrix),
                note=f"{note_prefix} {yield_note}",
            )
        if classification.use_key in COUNTY_USE_RULES:
            district_yields = [self._yield_for_code(parcel, code, parcel_area, shape_efficiency, None) for code in codes]
            conservative_yields = [item.conservative_yield or 0 for item in district_yields]
            gross_yields = [item.gross_area_yield or 0 for item in district_yields]
            return YieldRecommendation(
                development_option=title,
                status=self._permission_status(permission, bool(conservative_yields and min(conservative_yields) > 0)),
                conservative_yield=min(conservative_yields) if conservative_yields else None,
                gross_area_yield=min(gross_yields) if gross_yields else None,
                limiting_factors=tuple(dict.fromkeys(factor for item in district_yields for factor in item.limiting_factors)),
                note=f"{note_prefix} Residential yield remains conservative and must be checked against legal layout, frontage, access, and subdivision design.",
            )
        status = self._permission_status(permission, False)
        if permission == "":
            status = "Interpretation Required"
        return YieldRecommendation(
            development_option=title,
            status=status,
            conservative_yield=None,
            gross_area_yield=None,
            limiting_factors=("Use classification", "Bulk standard mapping"),
            note=(
                f"{note_prefix} The app found the use classification/permission screen, but does not yet have a reliable "
                "bulk-yield row for this use. If NCC determines this use is not enumerated, Sec. 40.03.110 directs the "
                "applicant to request an interpretation under Sec. 40.31.520."
            ),
        )

    def _yield_for_code(
        self,
        parcel: ParcelRecord,
        code: str,
        parcel_area: float,
        shape_efficiency: float,
        capacity_matrix: CapacityMatrix | None,
    ) -> YieldRecommendation:
        standard = COUNTY_RESIDENTIAL_STANDARDS.get(code)
        if not standard:
            return YieldRecommendation("", "Review Required", None, None, ("Bulk standard not encoded",), "")
        min_area = float(standard["min_lot_area"])
        if min_area <= 0:
            return YieldRecommendation("", "Review Required", None, None, ("Density table review required",), "")
        gross_yield = max(0, math.floor(parcel_area / min_area))
        if capacity_matrix is not None and code in COUNTY_RESIDENTIAL_CAPACITY_STANDARDS:
            gross_yield = capacity_matrix.maximum_yield
        shape_yield = max(0, math.floor((parcel_area * shape_efficiency) / min_area))
        if capacity_matrix is not None and code in COUNTY_RESIDENTIAL_CAPACITY_STANDARDS:
            shape_yield = min(shape_yield, capacity_matrix.maximum_yield)
        candidates = [shape_yield]
        limiting_factors = [f"{code} minimum lot area", "parcel shape/layout efficiency"]
        min_frontage = self._as_float(standard.get("min_frontage"))
        if parcel.frontage and min_frontage:
            frontage_yield = max(0, math.floor(parcel.frontage / min_frontage))
            candidates.append(frontage_yield)
            if frontage_yield < shape_yield:
                limiting_factors.append("available frontage")
        if gross_yield > shape_yield:
            limiting_factors.append("gross density exceeds conservative layout yield")
        return YieldRecommendation(
            development_option="",
            status="By Right",
            conservative_yield=min(candidates) if candidates else shape_yield,
            gross_area_yield=gross_yield,
            limiting_factors=tuple(limiting_factors),
            note="",
        )

    def _capacity_matrix_for_codes(
        self,
        codes: tuple[str, ...],
        parcel_area_sf: float,
        protected_resources: tuple[ProtectedResourceResult, ...],
    ) -> CapacityMatrix | None:
        standards = [COUNTY_RESIDENTIAL_CAPACITY_STANDARDS.get(code) for code in codes]
        standards = [standard for standard in standards if standard is not None]
        if not standards:
            nonres_standard = self._nonresidential_bulk_standard(codes, "office")
            if nonres_standard:
                return self._nonresidential_capacity_matrix(parcel_area_sf, protected_resources, nonres_standard, "office")
            return None
        standard = standards[0]
        base_site_area = parcel_area_sf / ACRE_SF
        total_resource_land = min(base_site_area, sum(resource.measured_acres for resource in protected_resources))
        total_protected_land = min(base_site_area, sum(resource.protected_acres for resource in protected_resources))
        total_unrestricted_land = max(0.0, base_site_area - total_resource_land)
        usability = standard["usability"]
        usable_land = total_unrestricted_land * usability
        site_protected_land = usable_land + total_protected_land
        open_space_ratio = standard["open_space"]
        minimum_open_space = base_site_area * open_space_ratio
        required_protected = max(site_protected_land, minimum_open_space)
        net_buildable = max(0.0, base_site_area - required_protected)
        net_density = standard["net_density"]
        site_yield = net_buildable * net_density
        gross_density = standard["gross_density"]
        district_yield = base_site_area * gross_density
        maximum_yield = max(0, math.floor(min(site_yield, district_yield)))
        return CapacityMatrix(
            capacity_type="residential",
            base_site_area_ac=base_site_area,
            total_resource_land_ac=total_resource_land,
            total_protected_land_ac=total_protected_land,
            total_unrestricted_land_ac=total_unrestricted_land,
            usability_factor=usability,
            usable_land_ac=usable_land,
            site_protected_land_ac=site_protected_land,
            minimum_open_space_ratio=open_space_ratio,
            minimum_open_space_ac=minimum_open_space,
            required_protected_land_ac=required_protected,
            net_buildable_site_area_ac=net_buildable,
            max_net_density=net_density,
            site_specific_density_yield=site_yield,
            max_gross_density=gross_density,
            district_density_yield=district_yield,
            maximum_yield=maximum_yield,
        )

    def _nonresidential_capacity_matrix(
        self,
        parcel_area_sf: float,
        protected_resources: tuple[ProtectedResourceResult, ...],
        standard: BulkStandard,
        use_key: str = "",
    ) -> CapacityMatrix:
        base_site_area = parcel_area_sf / ACRE_SF
        total_resource_land = min(base_site_area, sum(resource.measured_acres for resource in protected_resources))
        total_protected_land = min(base_site_area, sum(resource.protected_acres for resource in protected_resources))
        buildable_land_site = max(0.0, base_site_area - total_protected_land)
        minimum_landscape = base_site_area * standard.minimum_landscape_ratio
        buildable_land_district = max(0.0, base_site_area - minimum_landscape)
        limiting_buildable = min(buildable_land_site, buildable_land_district)
        site_floor_area_sf = math.floor(limiting_buildable * standard.maximum_net_far * ACRE_SF)
        district_floor_area_sf = math.floor(base_site_area * standard.maximum_gross_far * ACRE_SF)
        parking_floor_area_sf = self._parking_supported_floor_area(limiting_buildable * ACRE_SF, use_key, standard)
        maximum_floor_area_sf = max(0, min(site_floor_area_sf, district_floor_area_sf, parking_floor_area_sf))
        minimum_landscaped_surface = max(total_protected_land, minimum_landscape)
        return CapacityMatrix(
            capacity_type="nonresidential",
            base_site_area_ac=base_site_area,
            total_resource_land_ac=total_resource_land,
            total_protected_land_ac=total_protected_land,
            total_unrestricted_land_ac=max(0.0, base_site_area - total_resource_land),
            usability_factor=0.0,
            usable_land_ac=0.0,
            site_protected_land_ac=total_protected_land,
            minimum_open_space_ratio=0.0,
            minimum_open_space_ac=0.0,
            required_protected_land_ac=minimum_landscaped_surface,
            net_buildable_site_area_ac=limiting_buildable,
            max_net_density=standard.maximum_net_far,
            site_specific_density_yield=site_floor_area_sf,
            max_gross_density=standard.maximum_gross_far,
            district_density_yield=district_floor_area_sf,
            maximum_yield=maximum_floor_area_sf,
            minimum_landscape_ratio=standard.minimum_landscape_ratio,
            minimum_landscaped_area_ac=minimum_landscape,
            buildable_land_district_ac=buildable_land_district,
            max_net_far=standard.maximum_net_far,
            max_gross_far=standard.maximum_gross_far,
            site_specific_floor_area_sf=site_floor_area_sf,
            district_floor_area_sf=district_floor_area_sf,
            maximum_floor_area_sf=maximum_floor_area_sf,
        )

    def _parking_supported_floor_area(self, buildable_site_sf: float, use_key: str, standard: BulkStandard) -> int:
        if buildable_site_sf <= 0:
            return 0
        parking_ratio = self._nonresidential_parking_ratio(use_key, standard)
        parking_area_per_gfa_sf = (parking_ratio / 1000.0) * SURFACE_PARKING_AREA_PER_SPACE_SF
        required_site_per_gfa_sf = parking_area_per_gfa_sf + NONRESIDENTIAL_BUILDING_FOOTPRINT_SHARE
        if required_site_per_gfa_sf <= 0:
            return math.floor(buildable_site_sf)
        effective_site_sf = buildable_site_sf * NONRESIDENTIAL_SITE_SUPPORT_FACTOR * FIRE_ACCESS_SITE_FACTOR
        return max(0, math.floor(effective_site_sf / required_site_per_gfa_sf))

    def _nonresidential_parking_ratio(self, use_key: str, standard: BulkStandard) -> float:
        if use_key in NONRESIDENTIAL_PARKING_RATIOS:
            return NONRESIDENTIAL_PARKING_RATIOS[use_key]
        label = standard.use_label.lower()
        if "restaurant" in label:
            return NONRESIDENTIAL_PARKING_RATIOS["restaurant"]
        if "industrial" in label:
            return NONRESIDENTIAL_PARKING_RATIOS["industrial"]
        if "office" in label:
            return NONRESIDENTIAL_PARKING_RATIOS["office"]
        if "lodging" in label:
            return NONRESIDENTIAL_PARKING_RATIOS["commercial_lodging"]
        if "solar" in label:
            return NONRESIDENTIAL_PARKING_RATIOS["solar"]
        if "commercial" in label or "retail" in label:
            return NONRESIDENTIAL_PARKING_RATIOS["commercial"]
        return NONRESIDENTIAL_PARKING_RATIOS["other_permitted"]

    def _nonresidential_limiting_factors(self, matrix: CapacityMatrix | None) -> tuple[str, ...]:
        if matrix is None:
            return ("Municode Table 40.04.110 standards not available",)
        factors = ["protected resource land", "minimum landscaped surface"]
        if matrix.maximum_floor_area_sf < min(matrix.site_specific_floor_area_sf, matrix.district_floor_area_sf):
            factors.append("surface parking/fire access site support")
        elif matrix.site_specific_floor_area_sf <= matrix.district_floor_area_sf:
            factors.append("maximum net FAR")
        else:
            factors.append("maximum gross FAR")
        return tuple(factors)

    def _nonresidential_bulk_standard(self, codes: tuple[str, ...], use_key: str) -> BulkStandard | None:
        if use_key not in {
            "office",
            "commercial",
            "commercial_retail",
            "restaurant",
            "commercial_lodging",
            "heavy_retail",
            "industrial",
            "mixed_use",
            "institutional_regional",
            "institutional_neighborhood",
            "institutional_residential",
            "hospital",
            "school",
            "college",
            "other_permitted",
            "custom",
            "solar",
        }:
            return None
        if len(set(codes)) != 1:
            return None
        code = codes[0].upper()
        live = self._municode_bulk_standard(code, use_key)
        if live:
            return live
        return COUNTY_NONRESIDENTIAL_FALLBACK_STANDARDS.get((code, use_key))

    def _municode_bulk_standard(self, zoning_code: str, use_key: str) -> BulkStandard | None:
        rows = self._municode_bulk_standard_rows()
        if not rows:
            return None
        target = self._municode_use_label(use_key)
        in_district = False
        for row in rows:
            if self._row_is_district_header(row, zoning_code):
                in_district = True
                continue
            if in_district and self._row_is_any_district_header(row):
                return None
            labels = {target.lower(), f"{target.lower()}s"}
            if target.lower() == "commercial retail":
                labels.add("retail")
            if target.lower() == "mixed use":
                labels.add("mixed uses")
            if in_district and row and row[0].lower() in labels:
                return self._bulk_standard_from_row(zoning_code, row)
        return None

    def _municode_bulk_standard_rows(self) -> list[list[str]]:
        try:
            data = self._fetch_municode_json(
                "CodesContent",
                {"productId": str(NCC_MUNICODE_PRODUCT_ID), "nodeId": NCC_BULK_STANDARDS_NODE_ID},
            )
        except Exception:
            return []
        parser = _TableRowParser()
        for doc in data.get("Docs", []):
            if "40.04.110" in str(doc.get("Title", "")):
                parser.feed(str(doc.get("Content", "")))
        return parser.rows

    def _municode_use_label(self, use_key: str) -> str:
        return {
            "office": "Offices",
            "industrial": "Industrial",
            "commercial": "Commercial retail",
            "commercial_retail": "Commercial retail",
            "restaurant": "Restaurants",
            "commercial_lodging": "Commercial lodging",
            "heavy_retail": "Heavy retail and service",
            "mixed_use": "Mixed use",
            "institutional_regional": "Other permitted uses",
            "institutional_neighborhood": "Other permitted uses",
            "institutional_residential": "Other permitted uses",
            "hospital": "Other permitted uses",
            "school": "Other permitted uses",
            "college": "Other permitted uses",
            "other_permitted": "Other permitted uses",
            "custom": "Other permitted uses",
            "solar": "Other permitted uses",
        }.get(use_key, "Other permitted uses")

    def _use_permission(self, codes: tuple[str, ...], use_key: str) -> str:
        label = USE_TABLE_LABELS.get(use_key)
        return self._use_permission_for_label(codes, label or "")

    def _use_permission_for_label(self, codes: tuple[str, ...], label: str) -> str:
        if not label or not codes:
            return ""
        table = self._municode_use_table()
        if not table:
            return ""
        header, rows = table
        indices = [
            index
            for index, value in enumerate(header)
            if any(self._use_table_header_matches_code(value, code) for code in codes)
        ]
        if not indices:
            return ""
        row = next((item for item in rows if item and item[0].strip().lower() == label.lower()), None)
        if not row:
            return ""
        permissions = [self._clean_permission(row[index]) for index in indices if index < len(row)]
        if not permissions:
            return ""
        if any(permission == "N" for permission in permissions):
            return "N"
        if any(permission == "S" for permission in permissions):
            return "S"
        if any(permission == "L" for permission in permissions):
            return "L"
        if any(permission == "Y" for permission in permissions):
            return "Y"
        return ""

    def _clean_permission(self, value: str) -> str:
        text = value.strip().upper()
        return text[:1] if text[:1] in {"Y", "L", "S", "N"} else ""

    def _classify_intended_use(self, intended_use: str) -> UseClassification:
        requested = " ".join(intended_use.split())
        normalized = self._normalize_use_text(requested)
        table_labels = self._use_table_labels()
        for label in table_labels:
            if normalized == self._normalize_use_text(label):
                return UseClassification(requested, label, self._use_key_for_label(label), "High", "Exact match to the NCC use table.")
        definition_terms = self._municode_use_definition_terms()
        for term in definition_terms:
            if normalized == self._normalize_use_text(term):
                use_key = DEFINITION_TO_USE_KEY.get(self._normalize_use_text(term), self._use_key_for_label(term))
                return UseClassification(requested, USE_TABLE_LABELS.get(use_key, term), use_key, "High", "Exact match to a Sec. 40.33.200 defined use.")
        for phrase, (use_key, rationale) in ADVANCED_USE_ALIASES.items():
            if phrase in normalized:
                return UseClassification(requested, USE_TABLE_LABELS.get(use_key, "Other permitted uses"), use_key, "Medium", rationale)
        for term in definition_terms:
            clean_term = self._normalize_use_text(term)
            if clean_term and (clean_term in normalized or normalized in clean_term):
                use_key = DEFINITION_TO_USE_KEY.get(clean_term, self._use_key_for_label(term))
                return UseClassification(
                    requested,
                    USE_TABLE_LABELS.get(use_key, term),
                    use_key,
                    "Medium",
                    "Closest phrase match to a Sec. 40.33.200 defined use; confirm if project facts suggest a narrower classification.",
                )
        return UseClassification(
            requested,
            "Other permitted uses",
            "other_permitted",
            "Low",
            "No direct defined-use match found; screened conservatively as Other permitted uses pending NCC interpretation.",
        )

    def _use_table_labels(self) -> tuple[str, ...]:
        table = self._municode_use_table()
        if not table:
            return ()
        return tuple(row[0] for row in table[1] if row and self._use_table_label_looks_like_use(row[0]))

    def _use_table_label_looks_like_use(self, label: str) -> bool:
        clean = label.strip()
        if not clean or clean in {"Land Use", "Residential", "Institutional", "Commercial", "Industrial", "Temporary", "Other"}:
            return False
        return any(ch.isalpha() for ch in clean)

    def _municode_use_definition_terms(self) -> tuple[str, ...]:
        try:
            data = self._fetch_municode_json(
                "CodesContent",
                {"productId": str(NCC_MUNICODE_PRODUCT_ID), "nodeId": NCC_USE_DEFINITIONS_NODE_ID},
            )
        except Exception:
            return ()
        terms: list[str] = []
        for doc in data.get("Docs", []):
            title = str(doc.get("Title", ""))
            if "Sec. 40.33.2" not in title:
                continue
            parser = _DefinitionTermParser()
            parser.feed(str(doc.get("Content", "")))
            terms.extend(parser.terms)
        return tuple(dict.fromkeys(terms))

    def _normalize_use_text(self, value: str) -> str:
        return " ".join(
            "".join(ch.lower() if ch.isalnum() else " " for ch in value.replace("&", " and ")).split()
        )

    def _use_key_for_label(self, label: str) -> str:
        normalized = self._normalize_use_text(label)
        for use_key, table_label in USE_TABLE_LABELS.items():
            if normalized == self._normalize_use_text(table_label):
                return use_key
        if "commercial retail" in normalized:
            return "commercial_retail"
        if "restaurant" in normalized:
            return "restaurant"
        if "lodging" in normalized:
            return "commercial_lodging"
        if "office" in normalized:
            return "office"
        if "hospital" in normalized:
            return "hospital"
        if "school" in normalized:
            return "school"
        if "college" in normalized:
            return "college"
        if "institutional regional" in normalized:
            return "institutional_regional"
        if "institutional neighborhood" in normalized:
            return "institutional_neighborhood"
        if "institutional residential" in normalized:
            return "institutional_residential"
        if "industrial" in normalized or "industry" in normalized:
            return "industrial"
        if "mixed use" in normalized:
            return "mixed_use"
        if "solar" in normalized or "renewable" in normalized or "photovoltaic" in normalized:
            return "solar"
        return "other_permitted"

    def _use_table_header_matches_code(self, header: str, code: str) -> bool:
        clean_header = header.strip().upper()
        clean_code = code.strip().upper()
        if not clean_header or not clean_code:
            return False
        if clean_header == clean_code or clean_header.split()[0] == clean_code:
            return True
        if clean_header.startswith("NC ") and clean_code.startswith("NC"):
            return True
        return False

    def _commercial_apartment_unit_screen(
        self,
        codes: tuple[str, ...],
        parcel_area_sf: float,
        protected_resources: tuple[ProtectedResourceResult, ...],
    ) -> tuple[int, str]:
        base_site_area = parcel_area_sf / ACRE_SF
        protected_land = min(base_site_area, sum(resource.protected_acres for resource in protected_resources))
        potential_outdoor_area_sf = max(0.0, (base_site_area - protected_land) * ACRE_SF)
        outdoor_units = math.floor(potential_outdoor_area_sf / 500.0)
        gfa_units = self._commercial_apartment_gfa_units(codes, parcel_area_sf, protected_resources)
        candidates = [outdoor_units]
        if gfa_units > 0:
            candidates.append(gfa_units)
        units = min(candidates)
        caveat = (
            "Commercial apartments are a limited use under Municode Sec. 40.03.305 where allowed. "
            f"Screened units use the lesser of the objective 500 sf yard/balcony/deck/roof-area requirement "
            f"({outdoor_units:,} units) and a GFA-based apartment program ({gfa_units:,} units). "
            "Actual unit count also requires separate private apartment access, parking, circulation, architecture, "
            "and plan-level confirmation."
        )
        return units, caveat

    def _commercial_apartment_gfa_units(
        self,
        codes: tuple[str, ...],
        parcel_area_sf: float,
        protected_resources: tuple[ProtectedResourceResult, ...],
    ) -> int:
        standard = self._nonresidential_bulk_standard(codes, "other_permitted")
        if standard is None:
            standard = self._nonresidential_bulk_standard(codes, "custom")
        if standard is None:
            return 0
        matrix = self._nonresidential_capacity_matrix(parcel_area_sf, protected_resources, standard, "commercial_apartment")
        apartment_program_gfa = matrix.maximum_floor_area_sf * APARTMENT_PROGRAM_GFA_UTILIZATION
        gfa_units = max(0, math.floor(apartment_program_gfa / self._average_gross_unit_area()))
        site_units = self._site_supported_apartment_units(parcel_area_sf, matrix, commercial_gfa=0)
        return min(gfa_units, site_units)

    def _site_supported_apartment_units(self, parcel_area_sf: float, matrix: CapacityMatrix, commercial_gfa: int) -> int:
        site_area_sf = min(parcel_area_sf, matrix.net_buildable_site_area_ac * ACRE_SF)
        effective_site_sf = site_area_sf * APARTMENT_SITE_SUPPORT_FACTOR * FIRE_ACCESS_SITE_FACTOR
        return self._site_supported_units_from_area(effective_site_sf, commercial_gfa)

    def _site_supported_units_from_area(self, effective_site_sf: float, commercial_gfa: int) -> int:
        commercial_parking_sf = (commercial_gfa / 1000.0) * COMMERCIAL_PARKING_SPACES_PER_1000_SF * SURFACE_PARKING_AREA_PER_SPACE_SF
        remaining_site_sf = max(0.0, effective_site_sf - commercial_parking_sf)
        per_unit_site_sf = (
            APARTMENT_PARKING_SPACES_PER_UNIT * SURFACE_PARKING_AREA_PER_SPACE_SF
            + self._average_gross_unit_area() * APARTMENT_BUILDING_FOOTPRINT_SHARE
        )
        if per_unit_site_sf <= 0:
            return 0
        return max(0, math.floor(remaining_site_sf / per_unit_site_sf))

    def _permission_status(self, permission: str, has_yield: bool) -> str:
        if permission == "Y":
            return "By Right" if has_yield else "Review Required"
        if permission == "L":
            return "Limited Use Review"
        if permission == "S":
            return "Special Use Review"
        if permission == "N":
            return "Not By Right"
        return "By Right" if has_yield else "Review Required"

    def _municode_use_table(self) -> tuple[list[str], list[list[str]]] | None:
        try:
            data = self._fetch_municode_json(
                "CodesContent",
                {"productId": str(NCC_MUNICODE_PRODUCT_ID), "nodeId": NCC_USE_TABLE_NODE_ID},
            )
        except Exception:
            return None
        parser = _TableRowParser()
        for doc in data.get("Docs", []):
            if "40.03.110" in str(doc.get("Title", "")):
                parser.feed(str(doc.get("Content", "")))
        header = next((row for row in parser.rows if row and row[0] == "Land Use"), None)
        if not header:
            return None
        return header, parser.rows

    def _mixed_use_apartment_units(
        self,
        codes: tuple[str, ...],
        parcel: ParcelRecord,
        parcel_area_sf: float,
        shape_efficiency: float,
        protected_resources: tuple[ProtectedResourceResult, ...],
    ) -> int:
        if self._use_permission(codes, "apartment") != "Y":
            commercial_permission = self._use_permission(codes, "commercial_apartment")
            if commercial_permission in {"Y", "L", "S"}:
                units, _caveat = self._commercial_apartment_unit_screen(codes, parcel_area_sf, protected_resources)
                return units
            return 0
        if len(set(codes)) != 1:
            return 0
        density = self._residential_density_from_bulk_table(codes[0], "Apartments")
        if density is None:
            return 0
        open_space, gross_density, net_density = density
        base_site_area = parcel_area_sf / ACRE_SF
        total_protected_land = min(base_site_area, sum(resource.protected_acres for resource in protected_resources))
        required_protected = max(total_protected_land, base_site_area * open_space)
        net_buildable = max(0.0, base_site_area - required_protected)
        site_yield = net_buildable * net_density
        district_yield = base_site_area * gross_density
        shape_yield = (parcel_area_sf * shape_efficiency / ACRE_SF) * gross_density
        frontage_yield = math.inf
        return max(0, math.floor(min(site_yield, district_yield, shape_yield, frontage_yield)))

    def _residential_density_from_bulk_table(self, zoning_code: str, use_label: str) -> tuple[float, float, float] | None:
        rows = self._municode_bulk_standard_rows()
        in_district = False
        for row in rows:
            if self._row_is_district_header(row, zoning_code):
                in_district = True
                continue
            if in_district and self._row_is_any_district_header(row):
                return None
            if in_district and row and row[0].lower() == use_label.lower():
                open_space = self._as_float(row[1] if len(row) > 1 else None)
                gross_density = self._as_float(row[2] if len(row) > 2 else None)
                net_density = self._as_float(row[3] if len(row) > 3 else None)
                if open_space is not None and gross_density is not None and net_density is not None:
                    return open_space, gross_density, net_density
        return None

    def _row_is_district_header(self, row: list[str], zoning_code: str) -> bool:
        return any(f"({zoning_code})" in cell for cell in row)

    def _row_is_any_district_header(self, row: list[str]) -> bool:
        return bool(row) and any("(" in cell and ")" in cell for cell in row) and not self._as_float(row[1] if len(row) > 1 else None)

    def _bulk_standard_from_row(self, zoning_code: str, row: list[str]) -> BulkStandard | None:
        if len(row) < 7:
            return None
        landscape = self._as_float(row[1])
        gross_far = self._as_float(row[4])
        net_far = self._as_float(row[5])
        if landscape is None or gross_far is None or net_far is None:
            return None
        return BulkStandard(
            zoning_code=zoning_code,
            use_label=row[0],
            minimum_landscape_ratio=landscape,
            maximum_gross_far=gross_far,
            maximum_net_far=net_far,
            permission=row[6],
            minimum_site_area=row[7] if len(row) > 7 else "",
            minimum_lot_area=row[9] if len(row) > 9 else "",
            source="Municode Sec. 40.04.110, Table 40.04.110",
        )

    def _measure_protected_resources(self, parcel_geometry: dict, zoning_codes: tuple[str, ...]) -> tuple[ProtectedResourceResult, ...]:
        results: list[ProtectedResourceResult] = []
        claimed_union: dict | None = None
        specs = sorted(PROTECTED_RESOURCE_SPECS, key=lambda item: self._resource_ratio(item, zoning_codes), reverse=True)
        for spec in specs:
            clipped_geometries: list[dict] = []
            failed_layers: list[str] = []
            for layer_id in spec["layers"]:
                try:
                    clipped_geometries.extend(self._intersection_geometries(str(spec["service"]), int(layer_id), parcel_geometry))
                except RuntimeError as exc:
                    failed_layers.append(f"{layer_id}: {exc}")
            clipped_union = self._union_geometries(clipped_geometries)
            unique_geometries = self._subtract_claimed_geometry(clipped_union, claimed_union)
            unique_union = self._union_geometries(unique_geometries)
            measured = self._geometry_area_acres(unique_geometries)
            ratio = self._resource_ratio(spec, zoning_codes)
            note_parts = [str(spec.get("note", ""))] if spec.get("note") else []
            if failed_layers:
                note_parts.append("One or more GIS layers could not be measured in this run; review source layer availability.")
            results.append(
                ProtectedResourceResult(
                    name=str(spec["name"]),
                    measured_acres=measured,
                    protected_acres=measured * ratio,
                    ratio=ratio,
                    source=f"{spec['service']}/" + ",".join(str(layer) for layer in spec["layers"]),
                    note=" ".join(note_parts),
                )
            )
            if ratio > 0 and unique_union:
                claimed_union = self._union_geometries(([claimed_union] if claimed_union else []) + [unique_union])
        for name in UNMAPPED_PROTECTED_RESOURCES:
            results.append(
                ProtectedResourceResult(
                    name=name,
                    measured_acres=0.0,
                    protected_acres=0.0,
                    ratio=0.0,
                    source="Not mapped yet",
                    note="Workbook category retained; GIS layer mapping still needs confirmation.",
                )
            )
        return tuple(results)

    def _resource_ratio(self, spec: dict[str, object], zoning_codes: tuple[str, ...]) -> float:
        commercial = any(code.upper() in COMMERCIAL_RESOURCE_RATIO_DISTRICTS for code in zoning_codes)
        key = "commercial_ratio" if commercial else "other_ratio"
        return float(spec.get(key, spec.get("ratio", 0.0)))

    def _intersection_geometries(self, service_url: str, layer_id: int, parcel_geometry: dict) -> list[dict]:
        features = self._fetch_json(
            f"{service_url}/{layer_id}/query",
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
        ).get("features", [])
        if not features:
            return []
        parcel = dict(parcel_geometry)
        parcel["spatialReference"] = {"wkid": int(MAP_SPATIAL_REFERENCE)}
        geometries = []
        for feature in features:
            geometry = feature.get("geometry")
            if geometry and "rings" in geometry:
                geometry["spatialReference"] = {"wkid": int(MAP_SPATIAL_REFERENCE)}
                geometries.append(geometry)
        if not geometries:
            return []
        intersected = self._fetch_json(
            GEOMETRY_INTERSECT_URL,
            {
                "f": "json",
                "sr": MAP_SPATIAL_REFERENCE,
                "geometry": json.dumps({"geometryType": "esriGeometryPolygon", "geometry": parcel}, separators=(",", ":")),
                "geometries": json.dumps({"geometryType": "esriGeometryPolygon", "geometries": geometries}, separators=(",", ":")),
            },
        )
        return [geometry for geometry in (intersected.get("geometries") or []) if geometry.get("rings")]

    def _subtract_claimed_geometry(self, geometry: dict | None, claimed_geometry: dict | None) -> list[dict]:
        if not geometry or not geometry.get("rings"):
            return []
        if not claimed_geometry or not claimed_geometry.get("rings"):
            return [geometry]
        difference = self._fetch_json(
            GEOMETRY_DIFFERENCE_URL,
            {
                "f": "json",
                "sr": MAP_SPATIAL_REFERENCE,
                "geometries": json.dumps({"geometryType": "esriGeometryPolygon", "geometries": [geometry]}, separators=(",", ":")),
                "geometry": json.dumps({"geometryType": "esriGeometryPolygon", "geometry": claimed_geometry}, separators=(",", ":")),
            },
        )
        return [item for item in (difference.get("geometries") or []) if item.get("rings")]

    def _union_geometries(self, geometries: list[dict]) -> dict | None:
        clean = [geometry for geometry in geometries if geometry and geometry.get("rings")]
        if not clean:
            return None
        if len(clean) == 1:
            return clean[0]
        unioned = self._fetch_json(
            GEOMETRY_UNION_URL,
            {
                "f": "json",
                "sr": MAP_SPATIAL_REFERENCE,
                "geometries": json.dumps({"geometryType": "esriGeometryPolygon", "geometries": clean}, separators=(",", ":")),
            },
        )
        geometry = unioned.get("geometry") or {}
        return geometry if geometry.get("rings") else None

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

    def _protected_resource_lines(self, resources: tuple[ProtectedResourceResult, ...]) -> tuple[str, ...]:
        mapped = [resource for resource in resources if resource.measured_acres > 0 or resource.source != "Not mapped yet"]
        lines = ["Protected resource matrix:"]
        for resource in mapped:
            suffix = f" ({resource.note})" if resource.note else ""
            lines.append(
                f"{resource.name}: measured {resource.measured_acres:,.2f} ac, ratio {resource.ratio:.2f}, protected {resource.protected_acres:,.2f} ac{suffix}"
            )
        return tuple(lines)

    def _resource_warnings(self, resources: tuple[ProtectedResourceResult, ...]) -> tuple[str, ...]:
        warnings = [
            f"Warning: {resource.note}"
            for resource in resources
            if resource.measured_acres > 0 and resource.note
        ]
        return tuple(dict.fromkeys(warnings))

    def _municipal_recommendations(self) -> tuple[YieldRecommendation, ...]:
        return tuple(
            YieldRecommendation(
                development_option=option,
                status="Municipal Review Required",
                conservative_yield=None,
                gross_area_yield=None,
                limiting_factors=("Municipal ordinance not encoded",),
                note="Open municipal ordinance source to calculate permitted use and yield.",
            )
            for option in DEVELOPMENT_OPTIONS
        )

    def _parcel_standards(self, parcel: ParcelRecord, parcel_area: float, shape_efficiency: float) -> tuple[str, ...]:
        lines = [
            f"Calculated parcel area: {parcel_area:,.0f} sf ({parcel_area / 43560:,.2f} ac)",
            f"Conservative shape/layout efficiency: {shape_efficiency:.0%}",
            f"Existing GIS frontage: {parcel.frontage:,.1f} ft" if parcel.frontage else "Existing GIS frontage: not reported",
        ]
        return tuple(lines)

    def _county_dimensional_notes(self, codes: tuple[str, ...]) -> tuple[tuple[str, ...], bool]:
        notes: list[str] = []
        for code in codes:
            standard = COUNTY_RESIDENTIAL_STANDARDS.get(code)
            if not standard:
                continue
            notes.append(f"{code}: {standard['label']}. {standard['note']}")
        return tuple(notes), False

    def _county_zoning_url(self, code: str) -> str:
        try:
            data = self._fetch_json(
                COUNTY_ZONING_URL_QUERY_URL,
                {"f": "json", "where": f"UPPER(Link)='{code.upper()}'", "outFields": "URL", "returnGeometry": "false"},
            )
        except RuntimeError:
            return COUNTY_CODE_HOME
        features = data.get("features") or []
        if features:
            return self._clean((features[0].get("attributes") or {}).get("URL"))
        return COUNTY_CODE_HOME

    def _query_by_geometry(self, url: str, geometry: dict, out_fields: str) -> dict:
        return self._fetch_json(
            url,
            {
                "f": "json",
                "where": "1=1",
                "outFields": out_fields,
                "returnGeometry": "false",
                "geometry": json.dumps(geometry, separators=(",", ":")),
                "geometryType": "esriGeometryPolygon",
                "inSR": MAP_SPATIAL_REFERENCE,
                "spatialRel": "esriSpatialRelIntersects",
            },
        )

    def _query_by_point(self, url: str, polygon_geometry: dict, out_fields: str) -> dict:
        point = self._representative_point(polygon_geometry)
        return self._fetch_json(
            url,
            {
                "f": "json",
                "where": "1=1",
                "outFields": out_fields,
                "returnGeometry": "false",
                "geometry": json.dumps(point, separators=(",", ":")),
                "geometryType": "esriGeometryPoint",
                "inSR": MAP_SPATIAL_REFERENCE,
                "spatialRel": "esriSpatialRelIntersects",
            },
        )

    def _fetch_json(self, url: str, params: dict[str, str]) -> dict:
        encoded = urllib.parse.urlencode(params).encode("utf-8")
        last_error: RuntimeError | None = None
        for attempt in range(2):
            request = urllib.request.Request(url, data=encoded, method="POST")
            request.add_header("Content-Type", "application/x-www-form-urlencoded")
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    data = json.load(response)
            except urllib.error.HTTPError as exc:
                message = exc.reason or str(exc)
                try:
                    payload = json.loads(exc.read().decode("utf-8", errors="replace"))
                    error = payload.get("error") or {}
                    details = "; ".join(str(item) for item in error.get("details", []))
                    message = f"{error.get('message') or message} {details}".strip()
                except Exception:
                    pass
                last_error = RuntimeError(f"GIS request failed: {message}")
            else:
                error = data.get("error")
                if not error:
                    return data
                details = "; ".join(str(item) for item in error.get("details", []))
                message = f"{error.get('message') or 'Unknown GIS service error'} {details}".strip()
                last_error = RuntimeError(f"GIS request failed: {message}")
            if attempt == 0 and last_error and "Unable to complete operation" in str(last_error):
                time.sleep(0.4)
                continue
            break
        if last_error:
            raise last_error
        raise RuntimeError("GIS request failed: Unknown GIS service error")

    def _fetch_municode_json(self, path: str, params: dict[str, str]) -> dict:
        url = f"{MUNICODE_API_BASE}/{path}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "X-CSRF": "1",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}

    def _report_text(self, result: FeasibilityResult) -> str:
        districts = ", ".join(
            f"{district.code} ({district.description})" if district.description else district.code
            for district in result.zoning_districts
        ) or "-"
        best = self._best_recommendation(result.recommendations)
        sections = [
            "Zoning Feasibility Checker",
            "",
            self._report_headline(result, best),
            "",
            f"Parcel: {result.parcel.parcel_number}",
            f"Address: {result.parcel.address or '-'}",
            f"Owner: {result.parcel.owner or '-'}",
            f"Municipality: {result.municipality}",
            f"Zoning: {districts}",
            f"Best option: {self._best_option_text(best)}",
            "",
            "Details:",
            *(f"- {line}" for line in result.details),
            "",
            "Input Checks:",
            *self._report_input_check_table(result),
            "",
            "Yield Recommendations:",
            *self._report_recommendation_table(result.recommendations),
            "",
            "Yield Caveat:",
            f"- {YIELD_PLANNING_DISCLAIMER}",
            "",
            "Value Screen Logic:",
            *(f"- {line}" for line in VALUE_SCREEN_METHOD_LINES),
            "",
            "Footnotes/Caveats:",
            *self._report_footnote_lines(result),
            "",
            "Sources:",
            *(f"- {source}" for source in result.sources),
            *(f"- {source}" for source in VALUE_SCREEN_SOURCE_LINES),
            "",
            "Planning note: This is a preliminary screening tool, not a legal zoning determination.",
        ]
        return "\n".join(sections)

    def _best_recommendation(self, recommendations: tuple[YieldRecommendation, ...]) -> YieldRecommendation | None:
        if not recommendations:
            return None
        return max(recommendations, key=lambda item: (((item.market_value_low or 0) + (item.market_value_high or 0)) / 2, item.conservative_yield or 0))

    def _report_headline(self, result: FeasibilityResult, best: YieldRecommendation | None) -> str:
        if best and best.conservative_yield is not None:
            value = self._money_range(best.market_value_low, best.market_value_high) if best.market_value_low is not None and best.market_value_high is not None else "no value screen"
            if best.program_scenario:
                scenario = best.program_scenario
                return f"{result.status}: {best.development_option} ranked first with {scenario.modeled_units or 0:,} apartment units modeled within a {scenario.envelope_gfa or 0:,} sf GFA envelope and {value}"
            return f"{result.status}: {best.development_option} ranked first with {best.conservative_yield:,} recommended planning-level yield and {value}"
        return f"{result.status}: {result.summary}"

    def _best_option_text(self, best: YieldRecommendation | None) -> str:
        if not best:
            return "-"
        if best.program_scenario:
            scenario = best.program_scenario
            yield_text = f"{scenario.modeled_units or 0:,} units within {scenario.envelope_gfa or 0:,} sf GFA envelope"
        else:
            yield_text = "-" if best.conservative_yield is None else f"{best.conservative_yield:,}"
        value = self._money_range(best.market_value_low, best.market_value_high) if best.market_value_low is not None and best.market_value_high is not None else "-"
        return f"{best.development_option} ({yield_text}; {value} screen)"

    def _report_input_check_table(self, result: FeasibilityResult) -> tuple[str, ...]:
        rows = [
            ("Parcel area", f"{result.parcel_area_sf / ACRE_SF:,.2f} ac"),
            ("Shape efficiency", f"{result.shape_efficiency:.0%}"),
            ("Frontage", f"{result.parcel.frontage:,.1f} ft" if result.parcel.frontage else "not reported"),
        ]
        matrix = result.capacity_matrix
        if matrix:
            rows.extend([("Resource land*", f"{matrix.total_resource_land_ac:,.2f} ac"), ("Protected land*", f"{matrix.total_protected_land_ac:,.2f} ac")])
            if matrix.capacity_type == "nonresidential":
                rows.extend(
                    [
                        ("Landscape ratio", f"{matrix.minimum_landscape_ratio:.2f}"),
                        ("Min landscaped area", f"{matrix.minimum_landscaped_area_ac:,.2f} ac"),
                        ("Buildable land", f"{matrix.net_buildable_site_area_ac:,.2f} ac"),
                        ("Net/Gross FAR", f"{matrix.max_net_far:.2f} / {matrix.max_gross_far:.2f}"),
                        ("Floor area cap", f"{matrix.maximum_floor_area_sf:,} sf"),
                    ]
                )
            else:
                rows.extend(
                    [
                        ("Required open space", f"{matrix.required_protected_land_ac:,.2f} ac"),
                        ("Net buildable", f"{matrix.net_buildable_site_area_ac:,.2f} ac"),
                        ("Gross density cap", f"{matrix.district_density_yield:,.1f} units"),
                    ]
                )
        return self._format_report_table(("Check", "Value"), rows, (24, 18))

    def _report_recommendation_table(self, recommendations: tuple[YieldRecommendation, ...]) -> tuple[str, ...]:
        if not recommendations:
            return ("- No yield recommendations generated.",)
        rows = []
        for index, item in enumerate(recommendations, start=1):
            if item.program_scenario:
                scenario = item.program_scenario
                yield_text = f"{scenario.modeled_units or 0:,} units in {scenario.envelope_gfa or 0:,} sf envelope"
                gross_text = "-" if scenario.total_program_gfa is None else f"{scenario.total_program_gfa:,} sf program"
            else:
                yield_text = "-" if item.conservative_yield is None else f"{item.conservative_yield:,}"
                gross_text = "-" if item.gross_area_yield is None else f"{item.gross_area_yield:,}"
            value_text = self._money_range(item.market_value_low, item.market_value_high) if item.market_value_low is not None and item.market_value_high is not None else "-"
            rows.append((f"[{index}] {item.development_option}", item.status, yield_text, value_text, gross_text))
        return self._format_report_table(("Option", "Status", "Scenario", "Value", "Program"), rows, (34, 24, 24, 16, 18))

    def _format_report_table(self, headers: tuple[str, ...], rows: list[tuple[str, ...]], widths: tuple[int, ...]) -> tuple[str, ...]:
        lines = [
            "  ".join(value.ljust(width) for value, width in zip(headers, widths)),
            "  ".join("-" * width for width in widths),
        ]
        for row in rows:
            cells = []
            for value, width in zip(row, widths):
                text = str(value)
                cells.append((text[: width - 1] + ".") if len(text) > width else text.ljust(width))
            lines.append("  ".join(cells))
        return tuple(lines)

    def _report_footnote_lines(self, result: FeasibilityResult) -> tuple[str, ...]:
        lines = ["* Resource acreage is overlap-adjusted. Higher protection ratios claim acreage before lower-ratio resources."]
        lines.extend(line.removeprefix("Warning: ") for line in result.details if line.startswith("Warning: "))
        county = result.municipality == "Unincorporated New Castle County"
        for index, item in enumerate(result.recommendations, start=1):
            if item.status == "Not By Right" and not item.conservative_yield:
                continue
            source = COUNTY_CODE_HOME if county else (result.sources[0] if result.sources else "")
            if source:
                lines.append(f"[{index}] Code reference: {source}")
            if item.note:
                lines.append(f"[{index}] {item.note}")
            if item.limiting_factors:
                lines.append(f"[{index}] Limiting factors: {', '.join(item.limiting_factors)}.")
        return tuple(dict.fromkeys(lines))

    def _dedupe_districts(self, districts: list[ZoningDistrict]) -> tuple[ZoningDistrict, ...]:
        seen: set[str] = set()
        clean: list[ZoningDistrict] = []
        for district in districts:
            key = district.code.upper()
            if key in seen:
                continue
            seen.add(key)
            clean.append(district)
        return tuple(clean)

    def _first_attr(self, attributes: dict, names: tuple[str, ...]) -> object:
        for name in names:
            if name in attributes:
                return attributes[name]
        for key, value in attributes.items():
            if key.split(".")[-1] in names:
                return value
        return None

    def _representative_point(self, geometry: dict) -> dict:
        ring = max(geometry.get("rings", [[]]), key=len)
        if not ring:
            raise RuntimeError("Parcel geometry has no polygon ring.")
        x = sum(float(point[0]) for point in ring) / len(ring)
        y = sum(float(point[1]) for point in ring) / len(ring)
        return {"x": x, "y": y, "spatialReference": {"wkid": int(MAP_SPATIAL_REFERENCE)}}

    def _polygon_area(self, geometry: dict) -> float:
        total = 0.0
        for ring in geometry.get("rings", []):
            if len(ring) < 3:
                continue
            area = 0.0
            for index, point in enumerate(ring):
                next_point = ring[(index + 1) % len(ring)]
                area += float(point[0]) * float(next_point[1]) - float(next_point[0]) * float(point[1])
            total += area / 2
        return abs(total)

    def _polygon_perimeter(self, geometry: dict) -> float:
        perimeter = 0.0
        for ring in geometry.get("rings", []):
            for index in range(1, len(ring)):
                x1, y1 = float(ring[index - 1][0]), float(ring[index - 1][1])
                x2, y2 = float(ring[index][0]), float(ring[index][1])
                perimeter += ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        return perimeter

    def _shape_efficiency(self, geometry: dict) -> float:
        area = self._polygon_area(geometry)
        perimeter = self._polygon_perimeter(geometry)
        if area <= 0 or perimeter <= 0:
            return 0.5
        compactness = 4 * math.pi * area / (perimeter * perimeter)
        if compactness < 0.12:
            return 0.45
        if compactness < 0.20:
            return 0.55
        if compactness < 0.35:
            return 0.65
        return 0.75

    def _is_unincorporated_hint(self, value: str) -> bool:
        normalized = value.strip().upper()
        return (
            normalized in {"", "N", "NO", "NONE", "UNINCORPORATED"}
            or "HUNDRED" in normalized
        )

    def _as_float(self, value: object) -> float | None:
        try:
            if value in (None, ""):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _clean(self, value: object) -> str:
        if value is None:
            return ""
        return " ".join(str(value).split()).strip(" ,-")

    def _safe_file_part(self, value: str) -> str:
        cleaned = "".join(ch for ch in value if ch not in '<>:"/\\|?*')
        return " ".join(cleaned.split()).strip() or "Parcel"
