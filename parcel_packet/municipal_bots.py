from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys


PROJECT_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
BOT_CACHE_ROOT = PROJECT_ROOT / "cache" / "municipal-bots"
SECTION_CACHE_ROOT = PROJECT_ROOT / "cache" / "municipal-sections"
WILMINGTON_CODE_HOME = "https://library.municode.com/de/wilmington/codes/code_of_ordinances?nodeId=PTIIWICO_CH48ZO"
SMYRNA_CODE_HOME = "https://library.municode.com/de/smyrna/codes/code_of_ordinances"
NEWARK_CODE_HOME = "https://library.municode.com/de/newark/codes/code_of_ordinances"
MIDDLETOWN_CODE_HOME = "https://evogov.s3.us-west-2.amazonaws.com/126/media/302288.pdf"


@dataclass(frozen=True)
class DistrictProfile:
    code: str
    label: str
    ordinance_section: str
    source_url: str
    planning_note: str


@dataclass(frozen=True)
class MunicipalBotProfile:
    key: str
    display_name: str
    status: str
    code_home: str
    source_status: str
    source_notes: tuple[str, ...]
    known_districts: dict[str, DistrictProfile]
    dependency_sources: tuple[tuple[str, str], ...]
    next_tasks: tuple[str, ...]


@dataclass(frozen=True)
class MunicipalBotDoctrine:
    name: str
    required_questions: tuple[str, ...]
    dependency_categories: tuple[str, ...]


@dataclass(frozen=True)
class MunicipalRecommendationSpec:
    development_option: str
    status: str
    limiting_factors: tuple[str, ...]
    note: str
    conservative_yield: int | None = None
    gross_area_yield: int | None = None
    market_value_low: int | None = None
    market_value_high: int | None = None
    market_basis: str = ""


@dataclass(frozen=True)
class MunicipalProfileResult:
    status: str
    confidence: str
    summary: str
    details: tuple[str, ...]
    standards: tuple[str, ...]
    sources: tuple[str, ...]
    recommendations: tuple[MunicipalRecommendationSpec, ...]


@dataclass(frozen=True)
class WilmingtonGfaScreen:
    option: str
    status: str
    district_codes: tuple[str, ...]
    site_factor: float
    value_low_per_sf: float
    value_high_per_sf: float
    note: str
    limiting_factors: tuple[str, ...]


@dataclass(frozen=True)
class WilmingtonUseAnswer:
    option: str
    status: str
    district_codes: tuple[str, ...]
    note: str
    limiting_factors: tuple[str, ...]


COMMON_INTERDEPENDENT_CODE_AREAS: tuple[str, ...] = (
    "Zoning controls must be read with subdivision, building, fire access, streets, utilities, environmental, housing, historic-preservation, stormwater, and public-works requirements where applicable.",
    "Access to a street, highway, boulevard, alley, or legal easement and the character of adjoining parcels are material feasibility questions.",
    "Neighborhood character and political/entitlement risk can control practical feasibility even when a mapped district appears favorable.",
    "Unexpected capital items such as utility connection fees, road construction, cut/fill, frontage improvements, parking, stormwater, and fire-lane geometry must be screened before a confident development recommendation.",
)

GENERIC_DEPENDENCY_TERMS: dict[str, tuple[str, ...]] = {
    "district inventory": ("district", "districts", "zoning districts", "classification"),
    "use permissions": ("permitted use", "permitted uses", "principal use", "uses permitted", "use table"),
    "limited/special/conditional use": ("limited use", "special use", "conditional use", "special exception", "board approval"),
    "definitions": ("definition", "definitions", "shall mean"),
    "bulk/dimensional standards": ("density", "floor area", "far", "lot area", "setback", "height", "yard", "coverage"),
    "parking/loading": ("parking", "loading", "driveway", "vehicle"),
    "streets/access": ("street", "access", "frontage", "right-of-way", "highway", "road"),
    "subdivision/site plan": ("subdivision", "land development", "site plan", "record plan"),
    "utilities/fees": ("utility", "sewer", "water", "connection fee", "impact fee", "tap fee"),
    "stormwater/environment": ("stormwater", "floodplain", "wetland", "tree", "forest", "environment"),
    "fire/building": ("fire", "building code", "construction", "sprinkler"),
    "historic/overlay": ("historic", "overlay", "design review"),
    "procedure": ("hearing", "board of adjustment", "planning commission", "variance", "appeal"),
}

GENERIC_USE_FAMILY_TERMS: dict[str, tuple[str, ...]] = {
    "Residential / Mixed Residential": ("dwelling", "residential", "apartment", "townhouse", "row house", "single-family", "two-family", "multifamily", "multi-family"),
    "Commercial / Office / Retail": ("commercial", "retail", "office", "restaurant", "shop", "service", "hotel", "motel", "business"),
    "Institutional / Civic": ("institutional", "school", "church", "worship", "hospital", "community center", "municipal", "public", "charitable"),
    "Industrial / Utility": ("industrial", "manufacturing", "warehouse", "warehousing", "utility", "laboratory", "research", "storage"),
    "Custom / Emerging Uses": ("solar", "renewable", "telecom", "antenna", "marijuana", "horticultural", "parking", "data center"),
}

MUNICIPAL_BOT_DOCTRINE = MunicipalBotDoctrine(
    name="complete municipal code ecosystem",
    required_questions=(
        "Identify every zoning district returned by GIS or found in the municipality code, not only the district attached to the current parcel.",
        "Capture every district family: residential, commercial, office, industrial, institutional, civic/public, mixed-use, waterfront, planned, overlay, conservation, and other locally named districts.",
        "For each district, classify development uses as by-right, limited, special, conditional, accessory, prohibited, or undefined before running yield math.",
        "For each classified use, collect district-specific dimensional, density, FAR, lot, height, setback, yard, coverage, open-space, and design standards.",
        "Read use-specific standards together with parking, loading, access, frontage, streets, fire access, utilities, subdivision, stormwater, environmental, historic, fee, and procedure requirements.",
        "Treat split zoning and non-bounded district contact as a materiality question that can change the controlling standard.",
        "Withhold confident yield where any controlling district/use/dependency category is missing, and explain what remains unencoded.",
    ),
    dependency_categories=(
        "district_inventory",
        "commercial_institutional_districts",
        "use_permissions",
        "limited_special_conditions",
        "definitions",
        "density_bulk",
        "parking_loading",
        "streets_access",
        "subdivision",
        "utilities_fees",
        "stormwater_environment",
        "fire_building",
        "historic_overlays",
        "procedure",
        "calibration_records",
    ),
)


def _municode_url(slug: str) -> str:
    return f"https://library.municode.com/de/{slug}/codes/code_of_ordinances"


def _seed_municode_bot(key: str, display_name: str, slug: str, *notes: str) -> MunicipalBotProfile:
    return MunicipalBotProfile(
        key=key,
        display_name=display_name,
        status="Seed Bot Created",
        code_home=_municode_url(slug),
        source_status="Municode source candidate discovered; section map not encoded",
        source_notes=(
            f"{display_name} has a reachable Municode code source candidate.",
            "The bot must map every zoning district, by-right use, limited/special/conditional use path, bulk rule, parking/access rule, and cross-chapter dependency before issuing confident yield.",
            *notes,
        ),
        known_districts={},
        dependency_sources=(("Municipal code home", _municode_url(slug)),),
        next_tasks=(
            f"Confirm {display_name} zoning chapter, complete district inventory, use table, definitions, dimensional standards, parking, and development-review procedures.",
            f"Map {display_name} district codes returned by GIS to official code labels.",
            f"Add calibration parcels with known {display_name} approvals or recorded plans.",
        ),
    )


MUNICIPAL_BOTS: tuple[MunicipalBotProfile, ...] = (
    _seed_municode_bot("ARDEN", "Village of Arden", "arden"),
    _seed_municode_bot("ARDENCROFT", "Village of Ardencroft", "ardencroft"),
    _seed_municode_bot("ARDENTOWN", "Village of Ardentown", "ardentown"),
    _seed_municode_bot("BELLEFONTE", "Town of Bellefonte", "bellefonte"),
    _seed_municode_bot("CLAYTON", "Town of Clayton", "clayton"),
    _seed_municode_bot("DELAWARE CITY", "Delaware City", "delaware_city"),
    _seed_municode_bot("ELSMERE", "Town of Elsmere", "elsmere"),
    MunicipalBotProfile(
        key="WILMINGTON",
        display_name="City of Wilmington",
        status="Seed Profile Active",
        code_home=WILMINGTON_CODE_HOME,
        source_status="Municode Chapter 48 seed anchors encoded",
        source_notes=(
            "Chapter 48 zoning is the current seed source.",
            "R-5-C is not singularly important. The Wilmington bot must digest the full Chapter 48 district and use ecosystem before its recommendations are treated as mature.",
            "The bot has not yet encoded the complete Wilmington permitted-use, limited/special-use, dimensional, parking, subdivision, fee, access, or entitlement map.",
        ),
        known_districts={
            "R-1": DistrictProfile(
                code="R-1",
                label="One-family detached dwellings",
                ordinance_section="Sec. 48-131",
                source_url="https://library.municode.com/de/wilmington/codes/code_of_ordinances?nodeId=PTIIWICO_CH48ZO_ARTIVREDI_DIV2USRE_S48-131DI",
                planning_note="Detached residential context; screen lotting only after lot dimensions, frontage, subdivision, and neighborhood pattern are encoded.",
            ),
            "R-2": DistrictProfile(
                code="R-2",
                label="One-family detached and semidetached dwellings",
                ordinance_section="Sec. 48-132",
                source_url="https://library.municode.com/de/wilmington/codes/code_of_ordinances?nodeId=PTIIWICO_CH48ZO_ARTIVREDI_DIV2USRE_S48-132DI",
                planning_note="Detached/semidetached residential context; screen lotting only after dimensional, frontage, and subdivision controls are encoded.",
            ),
            "R-2-A": DistrictProfile(
                code="R-2-A",
                label="One-family detached and semidetached dwellings with conversions",
                ordinance_section="Sec. 48-133",
                source_url="https://library.municode.com/de/wilmington/codes/code_of_ordinances?nodeId=PTIIWICO_CH48ZO_ARTIVREDI_DIV2USRE_S48-133ADI",
                planning_note="Conversion and small apartment context requires board-approval and dimensional review before unit yield.",
            ),
            "R-3": DistrictProfile(
                code="R-3",
                label="One-family row houses",
                ordinance_section="Sec. 48-134",
                source_url=f"{WILMINGTON_CODE_HOME}_ARTIVDIRE_S48-134DI",
                planning_note="Row-house district context must be tested against lot frontage, neighborhood pattern, access, and any non-bounded zoning distinction.",
            ),
            "R-4": DistrictProfile(
                code="R-4",
                label="Row houses with conversions",
                ordinance_section="Sec. 48-135",
                source_url="https://library.municode.com/de/wilmington/codes/code_of_ordinances?nodeId=PTIIWICO_CH48ZO_ARTIVREDI_DIV2USRE_S48-135DI",
                planning_note="Row-house conversion and limited apartment context requires board-approval, lot area, frontage, and neighborhood-pattern review.",
            ),
            "R-5-A": DistrictProfile(
                code="R-5-A",
                label="Low-density apartment houses",
                ordinance_section="Sec. 48-136",
                source_url="https://library.municode.com/de/wilmington/codes/code_of_ordinances?nodeId=PTIIWICO_CH48ZO_ARTIVREDI_DIV2USRE_S48-136ADI",
                planning_note="Garden apartment context; FAR and height limits give a preliminary screen but parking, open area, and access still control design.",
            ),
            "R-5-A-1": DistrictProfile(
                code="R-5-A-1",
                label="Low-medium density apartment houses",
                ordinance_section="Sec. 48-137",
                source_url="https://library.municode.com/de/wilmington/codes/code_of_ordinances?nodeId=PTIIWICO_CH48ZO_ARTIVREDI_DIV2USRE_S48-137DI",
                planning_note="Low-medium apartment and compatible institutional context; FAR and height limits give a preliminary screen.",
            ),
            "R-5-B": DistrictProfile(
                code="R-5-B",
                label="Medium-density apartment houses",
                ordinance_section="Sec. 48-138",
                source_url="https://library.municode.com/de/wilmington/codes/code_of_ordinances?nodeId=PTIIWICO_CH48ZO_ARTIVREDI_DIV2USRE_S48-138BDI",
                planning_note="Medium-density apartment context; FAR gives a preliminary screen but parking, yards, and adjacency controls remain material.",
            ),
            "R-5-C": DistrictProfile(
                code="R-5-C",
                label="Apartment houses, high density",
                ordinance_section="Sec. 48-139",
                source_url=f"{WILMINGTON_CODE_HOME}_ARTIVDIRE_S48-139CDI",
                planning_note="High-density apartment district context cannot be converted into yield until dimensional, parking, access, and cross-chapter constraints are reconciled.",
            ),
            "C-1": DistrictProfile(
                code="C-1",
                label="Neighborhood shopping",
                ordinance_section="Sec. 48-191",
                source_url="https://library.municode.com/de/wilmington/codes/code_of_ordinances?nodeId=PTIIWICO_CH48ZO_ARTVCODI_DIV2USRE_S48-191DI",
                planning_note="Neighborhood commercial uses must be screened with permitted-use language plus parking/loading, adjacency, access, and surrounding residential-impact controls.",
            ),
            "C-2": DistrictProfile(
                code="C-2",
                label="Secondary business commercial centers",
                ordinance_section="Sec. 48-193",
                source_url="https://library.municode.com/de/wilmington/codes/code_of_ordinances?nodeId=PTIIWICO_CH48ZO_ARTVCODI_DIV2USRE_S48-193DI",
                planning_note="Secondary commercial center uses must be screened with highway/access context, parking/loading, and site-design controls.",
            ),
            "C-3": DistrictProfile(
                code="C-3",
                label="Central retail",
                ordinance_section="Sec. 48-195",
                source_url="https://library.municode.com/de/wilmington/codes/code_of_ordinances?nodeId=PTIIWICO_CH48ZO_ARTVCODI_DIV2USRE_S48-195DI",
                planning_note="Central retail uses must be screened with downtown commercial context, parking/loading, and any cross-referenced central business controls.",
            ),
            "C-4": DistrictProfile(
                code="C-4",
                label="Central office",
                ordinance_section="Sec. 48-196",
                source_url="https://library.municode.com/de/wilmington/codes/code_of_ordinances?nodeId=PTIIWICO_CH48ZO_ARTVCODI_DIV2USRE_S48-196DI",
                planning_note="Central office and civic-center context must be screened with high-density GFA, parking/loading, access, and downtown entitlement constraints.",
            ),
            "C-5": DistrictProfile(
                code="C-5",
                label="Heavy commercial",
                ordinance_section="Sec. 48-197",
                source_url="https://library.municode.com/de/wilmington/codes/code_of_ordinances?nodeId=PTIIWICO_CH48ZO_ARTVCODI_DIV2USRE_S48-197DI",
                planning_note="Heavy commercial uses must be screened with truck access, storage-yard impacts, parking/loading, and nearby residential protections.",
            ),
            "M-1": DistrictProfile(
                code="M-1",
                label="Light manufacturing",
                ordinance_section="Sec. 48-246",
                source_url="https://library.municode.com/de/wilmington/codes/code_of_ordinances?nodeId=PTIIWICO_CH48ZO_ARTVIMAINDI_DIV2USRE_S48-246DI",
                planning_note="Light manufacturing forbids new residential development and must be screened with industrial operations, utilities, access, loading, and environmental controls.",
            ),
            "M-2": DistrictProfile(
                code="M-2",
                label="General industrial",
                ordinance_section="Sec. 48-247",
                source_url="https://library.municode.com/de/wilmington/codes/code_of_ordinances?nodeId=PTIIWICO_CH48ZO_ARTVIMAINDI_DIV2USRE_S48-247DI",
                planning_note="General industrial uses are broad but require prohibited-use, board-approval, buffer, loading, access, and environmental impact review.",
            ),
            "W-1": DistrictProfile(
                code="W-1",
                label="Waterfront manufacturing",
                ordinance_section="Sec. 48-336",
                source_url="https://library.municode.com/de/wilmington/codes/code_of_ordinances?nodeId=PTIIWICO_CH48ZO_ARTVIIIWADI_DIV2USRE_S48-336DI",
                planning_note="Waterfront manufacturing must be screened with rail/water/highway access, industrial use permissions, floodplain, environmental, and waterfront constraints.",
            ),
            "W-2": DistrictProfile(
                code="W-2",
                label="Waterfront manufacturing/commercial",
                ordinance_section="Sec. 48-337",
                source_url="https://library.municode.com/de/wilmington/codes/code_of_ordinances?nodeId=PTIIWICO_CH48ZO_ARTVIIIWADI_DIV2USRE_S48-337DI",
                planning_note="Waterfront manufacturing/commercial uses must be screened across industrial, commercial, access, floodplain, environmental, and waterfront constraints.",
            ),
        },
        dependency_sources=(
            ("District regulations", f"{WILMINGTON_CODE_HOME}_ARTIVDIRE"),
            ("General provisions and definitions", f"{WILMINGTON_CODE_HOME}_ARTIINGE"),
            ("Height", f"{WILMINGTON_CODE_HOME}_ARTXHESURE_S48-151HE"),
            ("Lot dimensions", f"{WILMINGTON_CODE_HOME}_ARTXHESURE_S48-152MILODI"),
            ("Floor area ratio", f"{WILMINGTON_CODE_HOME}_ARTXHESURE_S48-153FLARRA"),
            ("Setbacks", f"{WILMINGTON_CODE_HOME}_ARTXHESURE_S48-154SE"),
            ("Rear yards", f"{WILMINGTON_CODE_HOME}_ARTXHESURE_S48-155REYA"),
            ("Side yards", f"{WILMINGTON_CODE_HOME}_ARTXHESURE_S48-156SIYA"),
            ("Off-street parking", f"{WILMINGTON_CODE_HOME}_ARTXIIOFSTPALORE_S48-443PASPACDWREUS"),
        ),
        next_tasks=(
            "Encode Wilmington's complete zoning district inventory, use permissions, limited/special/conditional use paths, and dimensional standards.",
            "Add zoning materiality testing for non-bounded district contact.",
            "Map access, parking, subdivision, utilities, fire access, fees, and entitlement risk.",
        ),
    ),
    MunicipalBotProfile(
        key="NEWARK",
        display_name="City of Newark",
        status="Seed Bot Created",
        code_home=NEWARK_CODE_HOME,
        source_status="Municode source candidate discovered; section map not encoded",
        source_notes=(
            "Newark has a reachable Municode code source candidate.",
            "The bot has not yet confirmed the complete district inventory, use permissions, limited/special/conditional use paths, and dependency anchors.",
            "Do not apply New Castle County yield logic to Newark parcels.",
        ),
        known_districts={},
        dependency_sources=(("Municipal code home", NEWARK_CODE_HOME),),
        next_tasks=(
            "Confirm Newark zoning chapter, complete district inventory, use table, definitions, dimensional standards, parking, and development-review procedures.",
            "Map Newark district codes returned by the NCC municipal zoning layer to official code labels.",
            "Add calibration parcels with known Newark approvals or recorded plans.",
        ),
    ),
    MunicipalBotProfile(
        key="MIDDLETOWN",
        display_name="Town of Middletown",
        status="Seed Bot Created",
        code_home=MIDDLETOWN_CODE_HOME,
        source_status="Official town zoning-code PDF source discovered; section cache extracted",
        source_notes=(
            "Middletown zoning is sourced from the town-hosted zoning-code PDF, not Municode.",
            "The PDF cache includes district designation, definitions, use and area regulations, off-street parking, landscape screening, conditional use permits, board of adjustment, interpretation, administration, and amendment sections.",
            "Do not apply New Castle County yield logic to Middletown parcels.",
        ),
        known_districts={
            "C-2": DistrictProfile(
                code="C-2",
                label="Secondary business commercial centers",
                ordinance_section="Middletown Zoning Code Section 4",
                source_url=MIDDLETOWN_CODE_HOME,
                planning_note="Commercial district context must be interpreted through the PDF use and area regulation tables, parking, access, conditional-use, and site-plan requirements.",
            ),
            "R-1-B": DistrictProfile(
                code="R-1-B",
                label="Single family residential, 12,500 sf minimum lot size",
                ordinance_section="Middletown Zoning Code Section 4",
                source_url=MIDDLETOWN_CODE_HOME,
                planning_note="Single-family residential context must be interpreted through minimum lot size, frontage, subdivision, access, and utility requirements.",
            ),
        },
        dependency_sources=(
            ("Middletown zoning-code PDF", MIDDLETOWN_CODE_HOME),
            ("Definitions", MIDDLETOWN_CODE_HOME),
            ("District designation", MIDDLETOWN_CODE_HOME),
            ("Use and area regulations", MIDDLETOWN_CODE_HOME),
            ("Off-street parking", MIDDLETOWN_CODE_HOME),
            ("Conditional use permits", MIDDLETOWN_CODE_HOME),
        ),
        next_tasks=(
            "Transform the Middletown PDF cache into structured district/use/bulk/parking tables.",
            "Map all Middletown district codes returned by the NCC municipal zoning layer to official code labels.",
            "Add calibration parcels with known Middletown approvals or recorded plans.",
        ),
    ),
    _seed_municode_bot("NEW CASTLE", "City of New Castle", "new_castle"),
    _seed_municode_bot("NEWPORT", "Town of Newport", "newport"),
    _seed_municode_bot("ODESSA", "Town of Odessa", "odessa"),
    MunicipalBotProfile(
        key="SMYRNA",
        display_name="Town of Smyrna",
        status="Seed Bot Created",
        code_home=SMYRNA_CODE_HOME,
        source_status="Municode source home verified; section map not encoded",
        source_notes=(
            "Smyrna's Municode source is reachable, but the seed bot has not yet mapped complete zoning/use/dimensional/dependency section anchors.",
            "Smyrna may implicate Kent County context as well as municipal code; jurisdiction checks must not assume NCC-only facts.",
        ),
        known_districts={},
        dependency_sources=(("Municipal code home", SMYRNA_CODE_HOME),),
        next_tasks=(
            "Confirm Smyrna zoning chapter, complete district inventory, use table, definitions, dimensional standards, parking, and development-review procedures.",
            "Map Smyrna district codes to official code labels.",
            "Add calibration parcels with known Smyrna approvals or recorded plans.",
        ),
    ),
    _seed_municode_bot("TOWNSEND", "Town of Townsend", "townsend"),
)


def municipal_bot_for(municipality: str) -> MunicipalBotProfile:
    normalized = municipality.upper()
    for profile in sorted(MUNICIPAL_BOTS, key=lambda item: len(item.key), reverse=True):
        if _municipality_matches(normalized, profile.key):
            return profile
    return MunicipalBotProfile(
        key=_generic_key(municipality),
        display_name=municipality or "Unknown Municipality",
        status="Seed Bot Required",
        code_home="",
        source_status="Authoritative code source not yet discovered",
        source_notes=("This incorporated jurisdiction needs its own municipal bot before PropSpector should calculate yield.",),
        known_districts={},
        dependency_sources=(),
        next_tasks=(
            "Identify the authoritative municipal code source.",
            "Map zoning districts, use permissions, dimensional standards, parking, access, subdivision, utilities, fees, environmental overlays, and public-review procedure.",
            "Add calibration parcels and recorded-plan checks.",
        ),
    )


def has_named_municipal_bot(municipality: str) -> bool:
    normalized = municipality.upper()
    return any(_municipality_matches(normalized, profile.key) for profile in MUNICIPAL_BOTS)


def district_label(code: str, fallback: str = "") -> str:
    normalized = normalize_municipal_zoning_code(code)
    for profile in MUNICIPAL_BOTS:
        district = profile.known_districts.get(normalized)
        if district:
            return district.label
    return fallback


def normalize_municipal_zoning_code(code: str) -> str:
    value = " ".join(str(code or "").upper().strip().split())
    value = re.sub(r"^\d+", "", value).strip()
    value = value.replace(" ", "")
    value = re.sub(r"^R-?(\d)([A-Z])(\d)$", r"R-\1-\2-\3", value)
    value = re.sub(r"^R-?(\d)([A-Z]+)$", r"R-\1-\2", value)
    value = re.sub(r"^R-?(\d)$", r"R-\1", value)
    value = re.sub(r"^([CMW])-?(\d)$", r"\1-\2", value)
    return value


def build_municipal_profile(
    municipality: str,
    parcel_area_acres: float,
    zoning_lines: tuple[str, ...],
    resource_warnings: tuple[str, ...],
    parcel_count: int,
) -> MunicipalProfileResult:
    profile = municipal_bot_for(municipality)
    non_bounded = len(zoning_lines) > 1
    if not zoning_lines:
        distinction = "Municipal zoning layer did not return a usable district in this run. PropSpector is preserving the jurisdiction result and withholding yield until zoning can be confirmed."
    elif non_bounded:
        distinction = "Important: a non-bounded zoning distinction is present. PropSpector must evaluate area materiality, buildable portion, access, and adjoining parcel context before choosing a controlling standard."
    else:
        distinction = "Mapped municipal zoning returned one district for the parcel geometry. Area materiality still needs confirmation before confident yield math."
    site_line = (
        f"Assembled-site input: {parcel_count} parcels are being reviewed together. Municipal access, lot-combination, and subdivision rules must be checked before treating the site as one zoning lot."
        if parcel_count > 1
        else "Single-parcel input: adjoining parcels still need to be checked for access, frontage, neighborhood pattern, and political feasibility context."
    )
    learning_lines = _learning_digest_lines(profile.key)
    doctrine_lines = (
        f"Municipal bot doctrine: {MUNICIPAL_BOT_DOCTRINE.name}.",
        *MUNICIPAL_BOT_DOCTRINE.required_questions,
    )
    details = (
        f"Jurisdiction bot: {profile.display_name} - {profile.status}.",
        f"Municipality: {municipality}",
        f"Parcel area screened: {parcel_area_acres:,.2f} ac",
        f"Source status: {profile.source_status}",
        distinction,
        site_line,
        *doctrine_lines,
        *learning_lines,
        *zoning_lines,
        *profile.source_notes,
        *COMMON_INTERDEPENDENT_CODE_AREAS,
        *resource_warnings,
    )
    sources = tuple(
        dict.fromkeys(
            [
                profile.code_home,
                *(district.source_url for district in profile.known_districts.values()),
                *(url for _label, url in profile.dependency_sources),
            ]
        )
    )
    recommendations = _municipal_recommendations(profile, zoning_lines, non_bounded, parcel_area_acres)
    has_yield = any(item.conservative_yield for item in recommendations)
    standards = (
        (
            f"Profile maturity: {profile.status}. It can issue preliminary encoded yield or prospecting screens where district, use, FAR/GFA, dimensional, and parking standards have been cached; final confidence still depends on unresolved cross-chapter and site-design review."
            if has_yield
            else f"Profile maturity: {profile.status}. It can resolve jurisdiction and zoning context, but it cannot yet issue a confident municipal yield."
        ),
        "Required maturity categories: " + ", ".join(MUNICIPAL_BOT_DOCTRINE.dependency_categories),
        "Next bot tasks: " + "; ".join(profile.next_tasks),
        "Journal rule: no single ordinance section controls until related direct and indirect regulations are reconciled.",
    )
    return MunicipalProfileResult(
        status=f"{profile.display_name} Preliminary Yield" if has_yield else f"{profile.display_name} Review Active",
        confidence="Medium-Low" if has_yield else "Low",
        summary=(
            f"The parcel is in {profile.display_name}. PropSpector has generated a preliminary municipal yield or prospecting screen from encoded district, use, FAR/GFA, and parking standards; unresolved cross-chapter and site-design items remain caveats."
            if has_yield
            else f"The parcel is in {profile.display_name}. PropSpector has activated a jurisdiction-specific interpretation profile and is withholding yield until that municipality's code dependencies are encoded."
        ),
        details=details,
        standards=standards,
        sources=tuple(source for source in sources if source) or ("Municipal source not yet confirmed",),
        recommendations=recommendations,
    )


def _municipal_recommendations(
    profile: MunicipalBotProfile,
    zoning_lines: tuple[str, ...],
    non_bounded: bool,
    parcel_area_acres: float,
) -> tuple[MunicipalRecommendationSpec, ...]:
    if profile.key == "WILMINGTON":
        return _wilmington_recommendations(profile, zoning_lines, non_bounded, parcel_area_acres)
    return _cached_municipal_recommendations(profile, zoning_lines)


def _cached_municipal_recommendations(
    profile: MunicipalBotProfile,
    zoning_lines: tuple[str, ...],
) -> tuple[MunicipalRecommendationSpec, ...]:
    sections = _municipal_section_cache(profile)
    if not sections:
        return (
            MunicipalRecommendationSpec(
                development_option="Municipal Code Cache Needed",
                status="Source Cache Required",
                limiting_factors=("rendered ordinance section cache", "district inventory", "use-permission matrix", "cross-chapter dependency map"),
                note=(
                    f"{profile.display_name} has a municipal bot, but no rendered ordinance section cache is available yet. "
                    "PropSpector will not pretend to know the local code; this bot needs a source ingestion pass before issuing district or use cards."
                ),
            ),
        )

    codes = _codes_from_zoning_lines(zoning_lines)
    matched = _matched_cached_sections(sections, codes)
    coverage = _coverage_from_cached_sections(sections)
    permissions = _permission_signals_from_cached_sections(sections)
    cards: list[MunicipalRecommendationSpec] = [
        MunicipalRecommendationSpec(
            development_option="Cached Code Interpreter",
            status="Cached Code Interpreter Active",
            limiting_factors=tuple(_top_items(coverage, 5)) or ("cached ordinance text",),
            note=(
                f"{profile.display_name} has {len(sections)} rendered cached section(s). "
                f"Mapped district signal: {', '.join(codes) if codes else 'not resolved from GIS in this run'}. "
                f"The bot is reading cached code before producing cards; strongest cached categories are {_sentence_list(_top_items(coverage, 4))}."
            ),
        )
    ]
    if matched:
        cards.append(
            MunicipalRecommendationSpec(
                development_option="Mapped District Section Match",
                status="District Cache Match",
                limiting_factors=tuple(_section_titles(matched[:4])),
                note=(
                    "PropSpector found cached ordinance section text that appears to correspond to the parcel's mapped district signal. "
                    "This is the source-backed district context the bot should use before considering yield, use translation, or entitlement risk."
                ),
            )
        )
    else:
        cards.append(
            MunicipalRecommendationSpec(
                development_option="Mapped District Section Match",
                status="District Mapping Needed",
                limiting_factors=("GIS district code", "official district label", "cached section anchor"),
                note=(
                    f"The cache is present for {profile.display_name}, but the current mapped district signal did not cleanly match a cached section title. "
                    "The bot should map the GIS district code to the municipality's official district label before issuing yield."
                ),
            )
        )

    for option, terms in GENERIC_USE_FAMILY_TERMS.items():
        family_sections = _sections_with_terms(sections, terms)
        if not family_sections:
            continue
        cards.append(
            MunicipalRecommendationSpec(
                development_option=option,
                status="Cached Use Answer",
                limiting_factors=tuple(_section_titles(family_sections[:4])),
                note=(
                    f"The {profile.display_name} cache contains {len(family_sections)} section(s) with {option.lower()} language. "
                    f"Permission signals found across the cache: {_permission_sentence(permissions)}. "
                    "This card is a source-backed use translator; final yield still needs district-specific dimensional, parking, access, and procedure rules."
                ),
            )
        )

    if permissions:
        cards.append(
            MunicipalRecommendationSpec(
                development_option="Permission Path Summary",
                status="Cached Permission Signals",
                limiting_factors=tuple(f"{key}: {value}" for key, value in permissions.items()),
                note=(
                    f"The cached code for {profile.display_name} contains permission-path signals instead of a blank placeholder: "
                    f"{_permission_sentence(permissions)}. The bot must separate by-right, limited, special, conditional, prohibited, and undefined uses before ranking development options."
                ),
            )
        )
    cards.append(
        MunicipalRecommendationSpec(
            development_option="Remaining Bot Work",
            status="Implementation Profile Needed",
            limiting_factors=("district-by-use matrix", "bulk and density parser", "parking/access parser", "calibration parcels"),
            note=(
                f"{profile.display_name} is now cache-aware, but it is not mature until the cached sections are transformed into structured district/use/bulk tables and tested against calibration parcels."
            ),
        )
    )
    return tuple(cards)


def _municipal_section_cache(profile: MunicipalBotProfile) -> tuple[dict[str, str], ...]:
    path = SECTION_CACHE_ROOT / profile.key.lower().replace(" ", "_") / "latest.json"
    if not path.exists():
        return ()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    if not isinstance(data, list):
        return ()
    sections: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if len(text) < 80:
            continue
        sections.append(
            {
                "query": str(item.get("query") or ""),
                "title": str(item.get("title") or item.get("query") or "Cached section"),
                "url": str(item.get("url") or ""),
                "text": text,
            }
        )
    return tuple(sections)


def _codes_from_zoning_lines(zoning_lines: tuple[str, ...]) -> tuple[str, ...]:
    codes: list[str] = []
    for line in zoning_lines:
        candidates = []
        district_match = re.search(r"(?:DISTRICT|OVERLAP|CONTACT):\s*([A-Z0-9-]+)", line.upper())
        if district_match:
            candidates.append(district_match.group(1))
        else:
            candidates.extend(re.findall(r"\b(?:\d+)?[A-Z]{1,4}-?\d(?:-?[A-Z])?(?:-?\d)?\b", line.upper()))
            candidates.extend(re.findall(r"\b[A-Z]{1,4}\b", line.upper()))
        for candidate in candidates:
            if candidate in {"GIS", "THE", "AND", "FOR", "NOT", "RUN", "AC"}:
                continue
            normalized = normalize_municipal_zoning_code(candidate)
            if normalized not in codes:
                codes.append(normalized)
    return tuple(codes)


def _matched_cached_sections(sections: tuple[dict[str, str], ...], codes: tuple[str, ...]) -> tuple[dict[str, str], ...]:
    if not codes:
        return ()
    matched: list[dict[str, str]] = []
    for section in sections:
        haystack = f"{section['title']}\n{section['query']}\n{section['text']}".upper()
        for code in codes:
            variants = {code, code.replace("-", ""), code.replace("-", " ")}
            if any(re.search(rf"(?<![A-Z0-9]){re.escape(variant)}(?![A-Z0-9])", haystack) for variant in variants if variant):
                matched.append(section)
                break
    return tuple(matched)


def _coverage_from_cached_sections(sections: tuple[dict[str, str], ...]) -> dict[str, int]:
    coverage: dict[str, int] = {}
    for section in sections:
        text = section["text"].lower()
        for category, terms in GENERIC_DEPENDENCY_TERMS.items():
            if any(term in text for term in terms):
                coverage[category] = coverage.get(category, 0) + 1
    return coverage


def _permission_signals_from_cached_sections(sections: tuple[dict[str, str], ...]) -> dict[str, int]:
    buckets = {
        "by-right": ("permitted as a matter of right", "permitted uses", "uses permitted", "principal use"),
        "limited": ("limited use",),
        "special": ("special use", "special exception"),
        "conditional": ("conditional use",),
        "board review": ("board approval", "board of adjustment", "zoning board"),
        "prohibited": ("prohibited", "not permitted"),
    }
    text = "\n".join(section["text"] for section in sections).lower()
    return {
        bucket: sum(text.count(term) for term in terms)
        for bucket, terms in buckets.items()
        if sum(text.count(term) for term in terms)
    }


def _sections_with_terms(sections: tuple[dict[str, str], ...], terms: tuple[str, ...]) -> tuple[dict[str, str], ...]:
    matched = [
        section
        for section in sections
        if any(term in section["text"].lower() for term in terms)
    ]
    return tuple(matched)


def _section_titles(sections: tuple[dict[str, str], ...] | list[dict[str, str]]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(section.get("title") or section.get("query") or "Cached section") for section in sections))


def _top_items(counts: dict[str, int], limit: int) -> tuple[str, ...]:
    return tuple(key for key, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit])


def _sentence_list(items: tuple[str, ...]) -> str:
    if not items:
        return "none yet"
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _permission_sentence(permissions: dict[str, int]) -> str:
    if not permissions:
        return "no explicit permission-path signals yet"
    return ", ".join(f"{key} ({value})" for key, value in permissions.items())


def _wilmington_recommendations(
    profile: MunicipalBotProfile,
    zoning_lines: tuple[str, ...],
    non_bounded: bool,
    parcel_area_acres: float,
) -> tuple[MunicipalRecommendationSpec, ...]:
    present_codes = _mentioned_district_codes(profile, zoning_lines)
    r5c = profile.known_districts.get("R-5-C")
    r3 = profile.known_districts.get("R-3")
    zoning_note = (
        "The parcel returned both Wilmington district contexts, so the app screens R-5-C as the measurable high-density apartment path and treats R-3 as zoning context until materiality is confirmed."
        if non_bounded
        else "The municipal zoning result returned a single mapped Wilmington district in this run, but dimensional and parking standards still control any yield."
    )
    recommendations: list[MunicipalRecommendationSpec] = []
    recommendations.extend(_wilmington_commercial_residential_inheritance_cards(profile, present_codes, parcel_area_acres))
    recommendations.extend(_wilmington_apartment_far_cards(profile, present_codes, parcel_area_acres, non_bounded))
    if "R-5-C" in present_codes and r5c:
        apartment_units, apartment_gfa, low_income, high_income = _wilmington_apartment_screen(parcel_area_acres, 6.0, 0.70, 950.0)
        recommendations.append(
            MunicipalRecommendationSpec(
                development_option="Apartments",
                status="Preliminary Municipal Yield",
                limiting_factors=(
                    r5c.ordinance_section,
                    "Sec. 48-153 FAR 6.0",
                    "Sec. 48-443 apartment parking at one space per two families",
                    "High-rise site support and structured/off-site parking feasibility",
                    "Neighborhood and entitlement context",
                ),
                note=(
                    f"{r5c.code} is labeled '{r5c.label}'. {zoning_note} "
                    "Screen uses FAR 6.0, a 70% high-rise residential program factor, and a 950 sf average gross unit size. "
                    "Parking is screened at one space per two families; final feasibility still depends on garage, off-site, or surface parking design."
                ),
                conservative_yield=apartment_units,
                gross_area_yield=apartment_gfa,
                market_value_low=low_income,
                market_value_high=high_income,
                market_basis=f"annual gross residential income proxy from {apartment_units:,} Wilmington apartment units",
            )
        )
    if "R-3" in present_codes and r3:
        rowhouse_lots = _wilmington_r3_rowhouse_screen(parcel_area_acres)
        recommendations.append(
            MunicipalRecommendationSpec(
                development_option="Rowhouse / One-Family",
                status="Municipal Context Review",
                limiting_factors=(
                    r3.ordinance_section,
                    "Non-bounded zoning distinction",
                    "Lot frontage",
                    "Street access",
                    "Neighborhood pattern",
                    "Subdivision controls",
                ),
                note=f"{r3.code} is labeled '{r3.label}'. Treat it as an important zoning-context signal unless measurable buildable area confirms it controls the parcel.",
                conservative_yield=rowhouse_lots,
                gross_area_yield=None,
                market_value_low=rowhouse_lots * 90_000 if rowhouse_lots else None,
                market_value_high=rowhouse_lots * 180_000 if rowhouse_lots else None,
                market_basis=f"lot sale value proxy from {rowhouse_lots:,} rowhouse lots" if rowhouse_lots else "",
            )
        )
    recommendations.extend(_wilmington_residential_context_cards(profile, present_codes))
    recommendations.extend(_wilmington_nonresidential_district_cards(profile, present_codes, parcel_area_acres))
    if not any(item.conservative_yield for item in recommendations):
        recommendations.extend(_wilmington_use_answer_cards(present_codes))
    district_specific_count = len(recommendations)
    if not _has_use_answer_for(present_codes):
        recommendations.extend(
            (
                MunicipalRecommendationSpec(
                    development_option="Commercial or Institutional",
                    status="Use Translation Required",
                    limiting_factors=("Use definition", "District permission", "Parking/loading", "Access", "Cross-chapter limitations"),
                    note="Wilmington commercial, institutional, or civic uses must be classified through the city use language before any GFA or feasibility ranking is trusted.",
                ),
                MunicipalRecommendationSpec(
                    development_option="Custom / Emerging Use",
                    status="Use Translation Required",
                    limiting_factors=("Defined use category", "Special standards", "Public ownership", "Political and entitlement context"),
                    note="Novel uses such as solar, hospital, school, utility, or other civic/private hybrids need a Wilmington-specific use translator before PropSpector ranks them.",
                ),
            )
        )
    if district_specific_count == 0:
        recommendations = [
            MunicipalRecommendationSpec(
                development_option="Wilmington Development Review",
                status=profile.status,
                limiting_factors=("Municipal zoning confirmation", "Code dependency map incomplete"),
                note="PropSpector identified Wilmington jurisdiction but did not receive a known Wilmington zoning district from the GIS layer.",
            ),
            *recommendations,
        ]
    return _rank_wilmington_recommendations(tuple(recommendations))


def _rank_wilmington_recommendations(
    recommendations: tuple[MunicipalRecommendationSpec, ...],
) -> tuple[MunicipalRecommendationSpec, ...]:
    def key(item: MunicipalRecommendationSpec) -> tuple[int, int, int]:
        has_yield = item.conservative_yield is not None or item.gross_area_yield is not None
        income = item.market_value_high if item.market_value_high is not None else -1
        return (1 if has_yield else 0, income, item.conservative_yield or item.gross_area_yield or 0)

    return tuple(sorted(recommendations, key=key, reverse=True))


def _wilmington_commercial_residential_inheritance_cards(
    profile: MunicipalBotProfile,
    present_codes: set[str],
    parcel_area_acres: float,
) -> tuple[MunicipalRecommendationSpec, ...]:
    if not present_codes & {"C-1", "C-2"}:
        return ()

    cards: list[MunicipalRecommendationSpec] = []
    c2 = profile.known_districts.get("C-2")
    c1 = profile.known_districts.get("C-1")
    r5c = profile.known_districts.get("R-5-C")

    if "C-2" in present_codes and c2 and r5c:
        apartment_units, apartment_gfa, low_income, high_income = _wilmington_apartment_screen(parcel_area_acres, 6.0, 0.70, 950.0)
        cards.append(
            MunicipalRecommendationSpec(
                development_option="Apartments",
                status="Preliminary Municipal Yield",
                limiting_factors=(
                    f"{c2.code} {c2.label} ({c2.ordinance_section})",
                    "Sec. 48-193(c)(1) permits R-5-C uses in C-2",
                    f"{r5c.code} {r5c.label} ({r5c.ordinance_section})",
                    "Sec. 48-153 FAR 6.0 R-5-C high-density apartment screen",
                    "Sec. 48-443 apartment parking at one space per two families",
                    "site access, fire-lane geometry, and structured/off-site parking feasibility",
                ),
                note=(
                    "C-2 is not only a small commercial GFA bucket. Sec. 48-193(c)(1) permits any use permitted in R-5-C, so high-density apartments are a real Wilmington prospecting path on C-2 parcels. "
                    "Screen uses FAR 6.0, a 70% residential program factor, and a 950 sf average gross unit size. Final yield still depends on parking, loading, fire access, design, and entitlement context."
                ),
                conservative_yield=apartment_units,
                gross_area_yield=apartment_gfa,
                market_value_low=low_income,
                market_value_high=high_income,
                market_basis=f"annual gross residential income proxy from {apartment_units:,} inherited C-2/R-5-C apartment units",
            )
        )
        mixed_allowed_gfa = _wilmington_mixed_use_allowed_gfa(parcel_area_acres)
        commercial_gfa, units, low_income, high_income = _wilmington_c2_mixed_use_screen(parcel_area_acres)
        cards.append(
            MunicipalRecommendationSpec(
                development_option="Mixed Use",
                status="Preliminary Municipal Yield",
                limiting_factors=(
                    f"{c2.code} {c2.label} ({c2.ordinance_section})",
                    "Sec. 48-193(c)(1) imports R-5-C and C-1 uses",
                    "R-5-C apartment permission plus C-1 neighborhood retail/service/office/restaurant uses",
                    "parking/loading under Wilmington commercial-district requirements",
                    "fire access, structured/off-site parking, and site-design moderation",
                ),
                note=(
                    f"C-2 can support a mixed residential/commercial prospecting path because it imports R-5-C apartment uses and C-1 commercial uses. "
                    f"Screen allocates the program to street-facing commercial and upper-floor residential, with residential unit support {units:,} and site support {units:,}. "
                    "This is a calibration screen for Wilmington C-2 sites like 2000 Pennsylvania Avenue, not a final record-plan certification."
                ),
                conservative_yield=mixed_allowed_gfa,
                gross_area_yield=commercial_gfa,
                market_value_low=low_income,
                market_value_high=high_income,
                market_basis=f"annual gross mixed-use income proxy from {units:,} apartments plus {commercial_gfa:,} sf commercial in C-2",
            )
        )
    elif "C-1" in present_codes and c1:
        conversion_units, conversion_gfa, low_income, high_income = _wilmington_apartment_screen(parcel_area_acres, 1.0, 0.48, 1_000.0)
        cards.append(
            MunicipalRecommendationSpec(
                development_option="Upper-Floor Residential Conversion",
                status="Preliminary Municipal Screen",
                limiting_factors=(
                    f"{c1.code} {c1.label} ({c1.ordinance_section})",
                    "Sec. 48-191(c)(2) conversion of certain three-story two-family buildings",
                    "1,000 sf lot area per family",
                    "600 sf minimum livable floor area",
                    "existing-building condition and parking/loading",
                ),
                note="C-1 has a narrower inherited residential path than C-2. This is only a conversion/reuse screen where the existing building form fits the ordinance condition.",
                conservative_yield=conversion_units,
                gross_area_yield=conversion_gfa,
                market_value_low=low_income,
                market_value_high=high_income,
                market_basis=f"annual gross residential income proxy from {conversion_units:,} C-1 conversion units",
            )
        )
    return tuple(cards)


def _wilmington_use_answer_cards(present_codes: set[str]) -> tuple[MunicipalRecommendationSpec, ...]:
    answers = (
        WilmingtonUseAnswer(
            option="Institutional / Civic Uses",
            status="District Use Answer",
            district_codes=("R-5-C", "R-5-B"),
            limiting_factors=(
                "Sec. 48-139(c) imports R-5-B permitted uses",
                "Sec. 48-138(c)(5) hospital/charitable institutions",
                "Sec. 48-138(c)(8) public health or public community center",
                "Sec. 48-138(c)(9) municipal police station",
                "parking and site-design controls",
            ),
            note=(
                "In R-5-C, institutional/civic potential is not unknown. R-5-C imports R-5-B permitted uses, and R-5-B permits hospitals other than infectious/contagious/addiction-only facilities, noncorrectional charitable institutions, public health/community centers, and municipal police stations. Treat these as real prospecting paths, still subject to parking, access, site design, and operational fit."
            ),
        ),
        WilmingtonUseAnswer(
            option="Ground-Floor Support Commercial",
            status="District Use Answer",
            district_codes=("R-5-C", "R-5-B"),
            limiting_factors=(
                "Sec. 48-138(c)(4) medical/professional office or restaurant with apartment house",
                "one parking space per 150 sf office space",
                "ground-floor story or below",
                "no external effects",
                "Sec. 48-139(d)(2) accessory convenience uses by board approval",
            ),
            note=(
                "Commercial support uses are partially answered in R-5-C. R-5-B allows medical/professional office or restaurant uses when operated with an apartment house and located at the ground-floor story or below with parking. R-5-C also allows tenant-serving convenience commodities/services as accessory uses by zoning board approval, with visibility and access limits."
            ),
        ),
        WilmingtonUseAnswer(
            option="R-3 Corner Commercial / Professional",
            status="Board Review Path",
            district_codes=("R-3",),
            limiting_factors=(
                "Sec. 48-134(d)(6) existing ground-floor corner commercial continuation/reactivation",
                "Sec. 48-134(d)(8) professional/medical office limits",
                "Sec. 48-134(d)(9) neighborhood retail/personal service exclusions",
                "Sec. 48-134(d)(10) office/bank corner-property limits",
                "zoning board approval",
            ),
            note=(
                "In R-3, commercial potential is narrow but not blank. The cached section supports board-review paths for certain existing ground-floor corner commercial uses, limited professional/medical offices, neighborhood retail/personal service corner uses with exclusions, and office/bank corner-property uses. These should be treated as entitlement-sensitive reuse paths, not broad by-right commercial yield."
            ),
        ),
        WilmingtonUseAnswer(
            option="School / Worship / Neighborhood Civic",
            status="District Use Answer",
            district_codes=("R-3", "R-2", "R-1"),
            limiting_factors=(
                "R-3 imports R-1 and R-2 permitted uses through Sec. 48-134(c)(1)",
                "school/worship/civic uses require inherited district conditions",
                "parking",
                "neighborhood character",
                "public review where triggered",
            ),
            note=(
                "R-3 inherits R-1 and R-2 permitted-use categories, so school, worship, and neighborhood civic possibilities are not generic unknowns. The bot still needs the inherited condition matrix and parking/access standards before ranking these against apartment or rowhouse feasibility."
            ),
        ),
        WilmingtonUseAnswer(
            option="Custom / Emerging Use Translator",
            status="Use Translator Active",
            district_codes=("R-5-C", "R-5-B", "R-3"),
            limiting_factors=(
                "hospital is already classified as institutional in R-5-B/R-5-C",
                "school/worship/civic uses are inherited in R-3 context",
                "solar/utility/telecom require use-specific section mapping",
                "public ownership and entitlement risk",
            ),
            note=(
                "Custom uses should now be translated against known Wilmington buckets instead of left as mystery text. Hospital routes to institutional/civic in R-5-B/R-5-C. School or worship routes to inherited residential civic categories where R-3/R-2/R-1 apply. Solar, utility, telecom, and similar emerging uses still need use-specific section mapping before ranking."
            ),
        ),
        WilmingtonUseAnswer(
            option="Commercial Use Translator",
            status="District Use Answer",
            district_codes=("C-1", "C-2", "C-3", "C-4", "C-5"),
            limiting_factors=(
                "C-1 neighborhood retail/service/office/restaurant",
                "C-2 hotels, contractor/service, recreation, assembly, shelter, broader commercial",
                "C-3 central retail and incidental wholesale/light fabrication",
                "C-4 central office with excluded C-3 uses",
                "C-5 heavy commercial/storage/auto/terminal/utility/horticulture/marijuana buffers",
            ),
            note=(
                "Commercial districts now route through district-specific use language instead of a generic commercial unknown. C-1 is neighborhood-scale retail/service/office/restaurant. C-2 expands into hotels, contractor/service businesses, commercial recreation, theaters, assembly, day care, shelters, and related uses. C-3 adds central retail and incidental wholesale/light fabrication. C-4 is central office with specific excluded C-3 uses. C-5 supports heavy commercial, storage yards, auto/body, terminals, utilities, horticulture, and regulated marijuana uses."
            ),
        ),
        WilmingtonUseAnswer(
            option="Commercial Board-Review Paths",
            status="Board Review Path",
            district_codes=("C-1", "C-2", "C-3", "C-4", "C-5"),
            limiting_factors=(
                "zoning board approval",
                "gas station / funeral / utility / conversion paths vary by district",
                "hours of operation",
                "parking/loading",
                "neighborhood or downtown design constraints",
            ),
            note=(
                "The cached commercial sections include board-review paths, not just by-right uses. The app should treat those as entitlement-sensitive options that may matter for prospecting, especially where a buyer is considering reuse, conversion, utility, parking, or higher-impact commercial activity."
            ),
        ),
        WilmingtonUseAnswer(
            option="Industrial Use Translator",
            status="District Use Answer",
            district_codes=("M-1", "M-2"),
            limiting_factors=(
                "M-1 research/lab/light manufacturing/warehousing/accessory office",
                "M-1 no new residential development",
                "M-2 broad industrial permission",
                "M-2 prohibited uses",
                "external effects and hazardous/fire controls",
            ),
            note=(
                "Industrial districts now answer the basic use question. M-1 supports research/lab, light manufacturing, warehousing/storage, accessory office, limited service/retail, restaurants, utilities, and related support uses, while prohibiting new residential development. M-2 broadly permits uses not otherwise prohibited, but contains prohibited uses, board-review heavy industrial paths, external-effects controls, and fire/environmental review triggers."
            ),
        ),
        WilmingtonUseAnswer(
            option="Waterfront Use Translator",
            status="District Use Answer",
            district_codes=("W-1", "W-2"),
            limiting_factors=(
                "W-1 manufacturing/warehousing/lab/terminal/bulk fuel",
                "W-2 manufacturing plus commercial office/retail/marine/recreation/parking",
                "waterfront review standards",
                "floodplain/environmental constraints",
                "rail/water/highway or arterial access",
            ),
            note=(
                "Waterfront districts now route to their own use family. W-1 is primarily waterfront manufacturing, warehousing, lab/research, terminals/yards, bulk fuel, accessory office, restaurants/lunchrooms, and public service. W-2 adds office/bank, retail/service, commercial marine, recreation, hydropower, parking, restaurants, and public service uses, with residential/hotel/institutional paths generally requiring board approval."
            ),
        ),
        WilmingtonUseAnswer(
            option="Nonresidential Custom / Emerging Use Translator",
            status="Use Translator Active",
            district_codes=("C-1", "C-2", "C-3", "C-4", "C-5", "M-1", "M-2", "W-1", "W-2"),
            limiting_factors=(
                "solar/utility/telecom/marijuana/horticulture/parking must map to district-specific language",
                "public ownership",
                "buffer zones",
                "hours of operation",
                "board or conditional-use triggers",
            ),
            note=(
                "Novel or custom nonresidential uses should be translated into the closest Wilmington code bucket. Utility and public-service uses are present in several commercial/industrial/waterfront districts. Marijuana and horticulture are explicit in C-5, M-1, M-2, W-1, and W-2 with buffer or operational controls. Solar is not yet fully mapped and should remain review-required until energy/utility language is encoded."
            ),
        ),
    )
    cards: list[MunicipalRecommendationSpec] = []
    for answer in answers:
        if not any(code in present_codes for code in answer.district_codes):
            continue
        cards.append(
            MunicipalRecommendationSpec(
                development_option=answer.option,
                status=answer.status,
                limiting_factors=answer.limiting_factors,
                note=answer.note,
            )
        )
    return tuple(cards)


def _has_use_answer_for(present_codes: set[str]) -> bool:
    return bool(present_codes & {"R-5-C", "R-5-B", "R-3", "R-2", "R-1", "C-1", "C-2", "C-3", "C-4", "C-5", "M-1", "M-2", "W-1", "W-2"})


def _wilmington_residential_context_cards(
    profile: MunicipalBotProfile,
    present_codes: set[str],
) -> tuple[MunicipalRecommendationSpec, ...]:
    handled = {"R-3", "R-5-A", "R-5-A-1", "R-5-B", "R-5-C"}
    matched = [
        profile.known_districts[code]
        for code in ("R-1", "R-2", "R-2-A", "R-4")
        if code in present_codes and code in profile.known_districts and code not in handled
    ]
    if not matched:
        return ()
    return (
        MunicipalRecommendationSpec(
            development_option="Residential District Context",
            status="Residential Matrix Required",
            limiting_factors=tuple(
                [
                    *(f"{district.code} {district.label} ({district.ordinance_section})" for district in matched),
                    "lot dimensions",
                    "frontage",
                    "conversion or board-approval standards",
                    "subdivision controls",
                    "neighborhood pattern",
                ]
            ),
            note=(
                "Wilmington low-density and conversion residential districts are recognized, but PropSpector needs the full lot-dimension, frontage, conversion, board-approval, and subdivision matrix before issuing lot or unit yield."
            ),
        ),
    )


def _wilmington_nonresidential_district_cards(
    profile: MunicipalBotProfile,
    present_codes: set[str],
    parcel_area_acres: float,
) -> tuple[MunicipalRecommendationSpec, ...]:
    screens = (
        WilmingtonGfaScreen(
            option="Neighborhood Commercial",
            status="Preliminary Municipal Screen",
            district_codes=("C-1",),
            site_factor=0.35,
            value_low_per_sf=18.0,
            value_high_per_sf=30.0,
            limiting_factors=("C-1 retail/service use list", "hours of operation", "parking/loading", "residential adjacency"),
            note="C-1 supports neighborhood retail, personal service, office/bank, restaurant/lunchroom, parking/garage, club/lodge, municipal police, and related uses by right, with several board-approval uses. GFA is a conservative site-program screen, not a code maximum.",
        ),
        WilmingtonGfaScreen(
            option="Secondary Commercial",
            status="Preliminary Municipal Screen",
            district_codes=("C-2",),
            site_factor=0.50,
            value_low_per_sf=18.0,
            value_high_per_sf=32.0,
            limiting_factors=("C-2 commercial center use list", "highway/access context", "parking/loading", "site design"),
            note="C-2 carries R-5-C and C-1 uses plus hotels/motels, contractor/service businesses, commercial recreation, theaters, assembly, day care, shelters, and related commercial uses. GFA is a conservative site-program screen.",
        ),
        WilmingtonGfaScreen(
            option="Central Retail",
            status="Preliminary Municipal Screen",
            district_codes=("C-3",),
            site_factor=1.25,
            value_low_per_sf=20.0,
            value_high_per_sf=36.0,
            limiting_factors=("C-3 central retail use list", "downtown context", "parking/loading", "upper-floor/light manufacturing limits"),
            note="C-3 supports C-2 uses plus central retail, incidental wholesale/storage, limited incidental fabrication, passenger terminal, and newspaper/printing uses. GFA is a downtown program screen pending dimensional encoding.",
        ),
        WilmingtonGfaScreen(
            option="Central Office",
            status="Preliminary Municipal Screen",
            district_codes=("C-4",),
            site_factor=3.00,
            value_low_per_sf=24.0,
            value_high_per_sf=42.0,
            limiting_factors=("C-4 central office use list", "excluded C-3 uses", "parking/loading", "downtown entitlement context"),
            note="C-4 is the central office district and permits buildings of any height with very high density by district purpose language. This is a conservative prospecting envelope, not the theoretical maximum.",
        ),
        WilmingtonGfaScreen(
            option="Heavy Commercial",
            status="Preliminary Municipal Screen",
            district_codes=("C-5",),
            site_factor=0.55,
            value_low_per_sf=12.0,
            value_high_per_sf=24.0,
            limiting_factors=("C-5 heavy commercial use list", "truck access", "storage yards", "parking/loading", "residential buffers"),
            note="C-5 supports C-3 uses plus storage warehouses/yards, auto service/body uses, hauling terminals, utility facilities, horticulture, and marijuana facilities subject to buffers. GFA is a conservative site-program screen.",
        ),
        WilmingtonGfaScreen(
            option="Light Industrial",
            status="Preliminary Municipal Screen",
            district_codes=("M-1",),
            site_factor=0.35,
            value_low_per_sf=9.0,
            value_high_per_sf=18.0,
            limiting_factors=("M-1 light industrial use list", "no new residential development", "external effects", "loading/access", "environmental controls"),
            note="M-1 supports research/lab, light manufacturing, warehousing/storage, accessory office, limited retail/service, restaurant, utilities, and related industrial support uses. New residential development is not permitted.",
        ),
        WilmingtonGfaScreen(
            option="General Industrial",
            status="Preliminary Municipal Screen",
            district_codes=("M-2",),
            site_factor=0.45,
            value_low_per_sf=8.0,
            value_high_per_sf=16.0,
            limiting_factors=("M-2 broad industrial permission", "prohibited heavy uses", "special exception uses", "fire/environmental controls", "rail/water/highway access"),
            note="M-2 broadly permits uses not otherwise prohibited by law, with explicit prohibited uses, board-approval heavy industrial paths, and external-effects controls. New ordinary residential use is prohibited.",
        ),
        WilmingtonGfaScreen(
            option="Waterfront Industrial",
            status="Preliminary Municipal Screen",
            district_codes=("W-1",),
            site_factor=0.40,
            value_low_per_sf=9.0,
            value_high_per_sf=18.0,
            limiting_factors=("W-1 waterfront manufacturing use list", "rail/water/highway access", "waterfront standards", "floodplain/environmental", "loading"),
            note="W-1 supports manufacturing, processing/repair, warehousing/wholesale, lab/research, terminals/yards, bulk fuel, accessory office, restaurants/lunchrooms, public service, and related uses. Waterfront and environmental controls are material.",
        ),
        WilmingtonGfaScreen(
            option="Waterfront Mixed Commercial",
            status="Preliminary Municipal Screen",
            district_codes=("W-2",),
            site_factor=0.65,
            value_low_per_sf=12.0,
            value_high_per_sf=26.0,
            limiting_factors=("W-2 manufacturing/commercial use list", "arterial access", "waterfront standards", "floodplain/environmental", "parking/loading"),
            note="W-2 supports manufacturing, warehousing, lab/research, office/bank, retail/service, commercial marine, commercial recreation, hydropower, parking, restaurant/lunchroom, and public service uses by right. Residential/hotel/institutional uses require board approval.",
        ),
    )
    cards: list[MunicipalRecommendationSpec] = []
    for screen in screens:
        matched = [profile.known_districts[code] for code in screen.district_codes if code in present_codes and code in profile.known_districts]
        if not matched:
            continue
        gfa = _wilmington_gfa_screen(parcel_area_acres, screen.site_factor)
        cards.append(
            MunicipalRecommendationSpec(
                development_option=screen.option,
                status=screen.status,
                limiting_factors=tuple(
                    [
                        *(f"{district.code} {district.label} ({district.ordinance_section})" for district in matched),
                        *screen.limiting_factors,
                    ]
                ),
                note=screen.note,
                conservative_yield=gfa,
                gross_area_yield=gfa,
                market_value_low=int(gfa * screen.value_low_per_sf),
                market_value_high=int(gfa * screen.value_high_per_sf),
                market_basis=f"annual gross lease proxy from {gfa:,} sf preliminary Wilmington {screen.option.lower()} envelope",
            )
        )
    return tuple(cards)


def _wilmington_apartment_far_cards(
    profile: MunicipalBotProfile,
    present_codes: set[str],
    parcel_area_acres: float,
    non_bounded: bool,
) -> tuple[MunicipalRecommendationSpec, ...]:
    screens = {
        "R-5-A": ("Garden Apartments", 0.75, 0.62, 1_050.0, "Sec. 48-153 FAR 0.75 for garden apartments; height is limited by the district purpose language."),
        "R-5-A-1": ("Low-Medium Apartments", 2.0, 0.66, 1_000.0, "Sec. 48-153 FAR 2.0 and five-story by-right height context."),
        "R-5-B": ("Medium-Density Apartments", 3.5, 0.68, 975.0, "Sec. 48-153 FAR 3.5 for medium-density apartment context."),
    }
    cards: list[MunicipalRecommendationSpec] = []
    for code, (option, far, program_factor, gross_unit_sf, basis) in screens.items():
        district = profile.known_districts.get(code)
        if code not in present_codes or not district:
            continue
        units, gfa, low_income, high_income = _wilmington_apartment_screen(parcel_area_acres, far, program_factor, gross_unit_sf)
        cards.append(
            MunicipalRecommendationSpec(
                development_option=option,
                status="Preliminary Municipal Yield",
                limiting_factors=(
                    f"{district.code} {district.label} ({district.ordinance_section})",
                    basis,
                    "Sec. 48-443 apartment parking",
                    "yards/setbacks",
                    "access/fire/site design",
                ),
                note=(
                    f"{district.code} is labeled '{district.label}'. "
                    f"Screen uses FAR {far:g}, a {program_factor:.0%} residential program factor, and {gross_unit_sf:,.0f} sf average gross unit size. "
                    + ("Split or non-bounded zoning materiality must be resolved. " if non_bounded else "")
                    + "Final feasibility depends on parking, yards, access, fire-lane geometry, and entitlement context."
                ),
                conservative_yield=units,
                gross_area_yield=gfa,
                market_value_low=low_income,
                market_value_high=high_income,
                market_basis=f"annual gross residential income proxy from {units:,} Wilmington apartment units",
            )
        )
    return tuple(cards)


def _wilmington_apartment_screen(parcel_area_acres: float, far: float, program_factor: float, gross_unit_sf: float) -> tuple[int, int, int, int]:
    site_sf = max(0.0, parcel_area_acres) * 43_560.0
    gross_far_area = int(site_sf * far)
    program_gfa = int(gross_far_area * program_factor)
    units = max(0, int(program_gfa / gross_unit_sf))
    low_monthly = (0.05 * 1300) + (0.45 * 1550) + (0.40 * 1850) + (0.10 * 2300)
    high_monthly = (0.05 * 1650) + (0.45 * 1950) + (0.40 * 2350) + (0.10 * 2900)
    return units, gross_far_area, int(units * low_monthly * 12), int(units * high_monthly * 12)


def _wilmington_c2_mixed_use_screen(parcel_area_acres: float) -> tuple[int, int, int, int]:
    site_sf = max(0.0, parcel_area_acres) * 43_560.0
    gross_far_area = int(site_sf * 6.0)
    commercial_gfa = int(gross_far_area * 0.06)
    residential_gfa = int(gross_far_area * 0.58)
    units = max(0, int(residential_gfa / 950.0))
    low_monthly = (0.05 * 1300) + (0.45 * 1550) + (0.40 * 1850) + (0.10 * 2300)
    high_monthly = (0.05 * 1650) + (0.45 * 1950) + (0.40 * 2350) + (0.10 * 2900)
    low_income = int(units * low_monthly * 12 + commercial_gfa * 18.0)
    high_income = int(units * high_monthly * 12 + commercial_gfa * 34.0)
    return commercial_gfa, units, low_income, high_income


def _wilmington_mixed_use_allowed_gfa(parcel_area_acres: float) -> int:
    site_sf = max(0.0, parcel_area_acres) * 43_560.0
    return int(site_sf * 6.0 * 0.64)


def _wilmington_gfa_screen(parcel_area_acres: float, site_factor: float) -> int:
    return max(0, int(max(0.0, parcel_area_acres) * 43_560.0 * site_factor))


def _wilmington_r3_rowhouse_screen(parcel_area_acres: float) -> int:
    site_sf = max(0.0, parcel_area_acres) * 43_560.0
    return max(0, int((site_sf * 0.65) / 1_600.0))


def _mentioned_district_codes(profile: MunicipalBotProfile, zoning_lines: tuple[str, ...]) -> set[str]:
    text = "\n".join(zoning_lines).upper()
    return {
        code
        for code in profile.known_districts
        if re.search(rf"(?<![A-Z0-9-]){re.escape(code)}(?![A-Z0-9-])", text)
    }


def _generic_key(municipality: str) -> str:
    key = "".join(character for character in municipality.upper() if character.isalnum() or character.isspace()).strip()
    return " ".join(key.split()) or "UNKNOWN"


def _learning_digest_lines(key: str) -> tuple[str, ...]:
    path = BOT_CACHE_ROOT / _safe_name(key) / "latest.json"
    if not path.exists():
        return ("Learning cache: no municipal learning pass has been recorded for this bot yet.",)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return (f"Learning cache: unreadable ({exc.__class__.__name__}).",)
    status = str(data.get("learn_status") or "Unknown")
    checked = str(data.get("checked_at") or "not recorded")
    coverage = data.get("dependency_coverage") or {}
    if isinstance(coverage, dict) and coverage:
        coverage_text = ", ".join(f"{category} ({count})" for category, count in coverage.items())
    else:
        coverage_text = "no dependency section candidates cached"
    sections = data.get("section_candidates") or []
    if isinstance(sections, list) and sections:
        sample = "; ".join(str(item.get("heading") or "-") for item in sections[:3] if isinstance(item, dict))
        sample_line = f"Learning cache sample sections: {sample}."
    else:
        sample_line = "Learning cache sample sections: none."
    return (
        f"Learning cache: {status}; checked {checked}; dependency coverage: {coverage_text}.",
        sample_line,
    )


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "UNKNOWN"


def _municipality_matches(normalized_municipality: str, key: str) -> bool:
    if normalized_municipality == key:
        return True
    return re.search(rf"\b{re.escape(key)}\b", normalized_municipality) is not None
