# Jurisdiction Expansion Matrix

| Jurisdiction | Status | Primary Code Source | GIS Zoning Source | Use Table | Bulk/Density | Parking | Environmental/Open Space | Calibration Parcels | Next Work |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Unincorporated New Castle County | Active | Municode Chapter 40 | NCC GIS zoning layers | Partially encoded | Partially encoded | Planning-level encoded | NCC environmental and WRPA services | 0804930379, 0902800058, 1105400001, 1000100014, 1000100074 | Continue record-plan calibration and refine limited-use conditions |
| City of Wilmington | Seed bot active | Municode Chapter 48 seed anchors | NCC municipal zoning layer | Not encoded | Not encoded | Not encoded | NCC environmental services usable; city rules not encoded | 1021 Gilpin Avenue / 2602130233 | Encode Wilmington use, bulk, parking, access, subdivision, fee, and entitlement dependencies before yield |
| Newark | Seed bot created | eCode source needs section confirmation | NCC municipal zoning layer | Not encoded | Not encoded | Not encoded | NCC environmental services usable; city rules not encoded | Needed | Confirm source anchors and encode Newark profile |
| Middletown | Seed bot created | eCode source needs section confirmation | NCC municipal zoning layer | Not encoded | Not encoded | Not encoded | NCC environmental services usable; town rules not encoded | Needed | Confirm source anchors and encode Middletown profile |
| Smyrna | Seed bot created | Municode source home verified | Smyrna/other GIS source needed | Not encoded | Not encoded | Not encoded | Municipal/county environmental context not encoded | Needed | Confirm source anchors and jurisdiction GIS sources |
| Other NCC Incorporated Municipalities | Seed bots created | Municode source candidates discovered | NCC municipal zoning layer where applicable | Not encoded | Not encoded | Not encoded | NCC environmental services usable where in NCC | Needed | Learn section maps and add calibration parcels |
| Other NCC Municipalities | Not encoded | Municipal code source needed | NCC municipal zoning layer | Not encoded | Not encoded | Not encoded | NCC environmental services usable; municipal rules not encoded | Needed | Prioritize by project frequency |

## Expansion Rule

Do not silently fall back to county logic for an incorporated municipality. If a municipality profile is missing, the app should clearly state that municipal code review is required.
