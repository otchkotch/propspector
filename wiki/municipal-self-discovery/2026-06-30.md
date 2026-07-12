# Municipal Self-Discovery Audit - 2026-06-30T22:29:34

## Purpose

This audit enforces the PropSpector rule that every municipal bot must seek source material, cache it, read it, interpret it, and avoid generic placeholder cards wherever cached code can answer the question.

## Coverage

| Bot | Sections | Learning Status | Source-Backed Answers | Queue Reason |
| --- | ---: | --- | --- | --- |
| Village of Arden | 0 | Municode shell reachable; ordinance content not exposed in page HTML | No | Needs rendered ordinance section cache |
| Village of Ardencroft | 0 | Municode shell reachable; ordinance content not exposed in page HTML | No | Needs rendered ordinance section cache |
| Village of Ardentown | 0 | Municode shell reachable; ordinance content not exposed in page HTML | No | Needs rendered ordinance section cache |
| Town of Bellefonte | 0 | Municode shell reachable; ordinance content not exposed in page HTML | No | Needs rendered ordinance section cache |
| Town of Clayton | 5 | Rendered source extracted into section cache | Yes | - |
| Delaware City | 17 | Rendered source extracted into section cache | Yes | - |
| Town of Elsmere | 0 | Municode shell reachable; ordinance content not exposed in page HTML | No | Needs rendered ordinance section cache |
| City of Wilmington | 26 | Rendered source extracted into section cache | Yes | - |
| City of Newark | 16 | Rendered source extracted into section cache | Yes | - |
| Town of Middletown | 31 | Official PDF source cached; existing extracted sections available | Yes | - |
| City of New Castle | 0 | Municode shell reachable; ordinance content not exposed in page HTML | No | Needs rendered ordinance section cache |
| Town of Newport | 0 | Municode shell reachable; ordinance content not exposed in page HTML | No | Needs rendered ordinance section cache |
| Town of Odessa | 0 | Municode shell reachable; ordinance content not exposed in page HTML | No | Needs rendered ordinance section cache |
| Town of Smyrna | 15 | Rendered source extracted into section cache | Yes | - |
| Town of Townsend | 0 | Municode shell reachable; ordinance content not exposed in page HTML | No | Needs rendered ordinance section cache |

## Ingestion Queue

- **Village of Arden**: Needs rendered ordinance section cache; source: https://library.municode.com/de/arden/codes/code_of_ordinances
- **Village of Ardencroft**: Needs rendered ordinance section cache; source: https://library.municode.com/de/ardencroft/codes/code_of_ordinances
- **Village of Ardentown**: Needs rendered ordinance section cache; source: https://library.municode.com/de/ardentown/codes/code_of_ordinances
- **Town of Bellefonte**: Needs rendered ordinance section cache; source: https://library.municode.com/de/bellefonte/codes/code_of_ordinances
- **Town of Elsmere**: Needs rendered ordinance section cache; source: https://library.municode.com/de/elsmere/codes/code_of_ordinances
- **City of New Castle**: Needs rendered ordinance section cache; source: https://library.municode.com/de/new_castle/codes/code_of_ordinances
- **Town of Newport**: Needs rendered ordinance section cache; source: https://library.municode.com/de/newport/codes/code_of_ordinances
- **Town of Odessa**: Needs rendered ordinance section cache; source: https://library.municode.com/de/odessa/codes/code_of_ordinances
- **Town of Townsend**: Needs rendered ordinance section cache; source: https://library.municode.com/de/townsend/codes/code_of_ordinances

## Details

### Village of Arden

- **Code home**: https://library.municode.com/de/arden/codes/code_of_ordinances
- **Cached sections**: 0
- **Learning status**: Municode shell reachable; ordinance content not exposed in page HTML
- **Dependency coverage**: -
- **Sample zoning**: Municipal zoning district: UNKNOWN (unmapped).
- **Recommendation statuses**: Source Cache Required
- **Queue reason**: Needs rendered ordinance section cache

### Village of Ardencroft

- **Code home**: https://library.municode.com/de/ardencroft/codes/code_of_ordinances
- **Cached sections**: 0
- **Learning status**: Municode shell reachable; ordinance content not exposed in page HTML
- **Dependency coverage**: -
- **Sample zoning**: Municipal zoning district: UNKNOWN (unmapped).
- **Recommendation statuses**: Source Cache Required
- **Queue reason**: Needs rendered ordinance section cache

### Village of Ardentown

- **Code home**: https://library.municode.com/de/ardentown/codes/code_of_ordinances
- **Cached sections**: 0
- **Learning status**: Municode shell reachable; ordinance content not exposed in page HTML
- **Dependency coverage**: -
- **Sample zoning**: Municipal zoning district: UNKNOWN (unmapped).
- **Recommendation statuses**: Source Cache Required
- **Queue reason**: Needs rendered ordinance section cache

### Town of Bellefonte

- **Code home**: https://library.municode.com/de/bellefonte/codes/code_of_ordinances
- **Cached sections**: 0
- **Learning status**: Municode shell reachable; ordinance content not exposed in page HTML
- **Dependency coverage**: -
- **Sample zoning**: Municipal zoning district: UNKNOWN (unmapped).
- **Recommendation statuses**: Source Cache Required
- **Queue reason**: Needs rendered ordinance section cache

### Town of Clayton

- **Code home**: https://library.municode.com/de/clayton/codes/code_of_ordinances
- **Cached sections**: 5
- **Learning status**: Rendered source extracted into section cache
- **Dependency coverage**: -
- **Sample zoning**: Municipal zoning district: UNKNOWN (unmapped).
- **Recommendation statuses**: Cached Code Interpreter Active, District Mapping Needed, Cached Use Answer, Cached Use Answer, Cached Use Answer, Cached Use Answer, Cached Use Answer, Cached Permission Signals
- **Queue reason**: -

### Delaware City

- **Code home**: https://library.municode.com/de/delaware_city/codes/code_of_ordinances
- **Cached sections**: 17
- **Learning status**: Rendered source extracted into section cache
- **Dependency coverage**: -
- **Sample zoning**: Municipal zoning district: MS4 (Sec. 31-7. - Suspension of MS4 access.).
- **Recommendation statuses**: Cached Code Interpreter Active, District Cache Match, Cached Use Answer, Cached Use Answer, Cached Use Answer, Cached Use Answer, Cached Use Answer, Cached Permission Signals
- **Queue reason**: -

### Town of Elsmere

- **Code home**: https://library.municode.com/de/elsmere/codes/code_of_ordinances
- **Cached sections**: 0
- **Learning status**: Municode shell reachable; ordinance content not exposed in page HTML
- **Dependency coverage**: -
- **Sample zoning**: Municipal zoning district: UNKNOWN (unmapped).
- **Recommendation statuses**: Source Cache Required
- **Queue reason**: Needs rendered ordinance section cache

### City of Wilmington

- **Code home**: https://library.municode.com/de/wilmington/codes/code_of_ordinances?nodeId=PTIIWICO_CH48ZO
- **Cached sections**: 26
- **Learning status**: Rendered source extracted into section cache
- **Dependency coverage**: district_inventory:28, commercial_institutional_districts:23, use_permissions:18, limited_special_conditions:7, definitions:1, density_bulk:24, parking_loading:28, streets_access:24, utilities_fees:16, stormwater_environment:20, fire_building:12, historic_overlays:2, procedure:20
- **Sample zoning**: Municipal zoning district: C-2 (Secondary business commercial centers).
- **Recommendation statuses**: Preliminary Municipal Yield, Preliminary Municipal Yield, Preliminary Municipal Screen
- **Queue reason**: -

### City of Newark

- **Code home**: https://library.municode.com/de/newark/codes/code_of_ordinances
- **Cached sections**: 16
- **Learning status**: Rendered source extracted into section cache
- **Dependency coverage**: district_inventory:1, commercial_institutional_districts:2, limited_special_conditions:1, definitions:1, density_bulk:1, parking_loading:2, subdivision:2, streets_access:2, utilities_fees:2, stormwater_environment:2, fire_building:1, procedure:1
- **Sample zoning**: Municipal zoning district: UNKNOWN (unmapped).
- **Recommendation statuses**: Cached Code Interpreter Active, District Mapping Needed, Cached Use Answer, Cached Use Answer, Cached Use Answer, Cached Use Answer, Cached Use Answer, Cached Permission Signals
- **Queue reason**: -

### Town of Middletown

- **Code home**: https://evogov.s3.us-west-2.amazonaws.com/126/media/302288.pdf
- **Cached sections**: 31
- **Learning status**: Official PDF source cached; existing extracted sections available
- **Dependency coverage**: -
- **Sample zoning**: Municipal zoning district: C-2 (Secondary business commercial centers).
- **Recommendation statuses**: Cached Code Interpreter Active, District Cache Match, Cached Use Answer, Cached Use Answer, Cached Use Answer, Cached Use Answer, Cached Use Answer, Cached Permission Signals
- **Queue reason**: -

### City of New Castle

- **Code home**: https://library.municode.com/de/new_castle/codes/code_of_ordinances
- **Cached sections**: 0
- **Learning status**: Municode shell reachable; ordinance content not exposed in page HTML
- **Dependency coverage**: -
- **Sample zoning**: Municipal zoning district: UNKNOWN (unmapped).
- **Recommendation statuses**: Source Cache Required
- **Queue reason**: Needs rendered ordinance section cache

### Town of Newport

- **Code home**: https://library.municode.com/de/newport/codes/code_of_ordinances
- **Cached sections**: 0
- **Learning status**: Municode shell reachable; ordinance content not exposed in page HTML
- **Dependency coverage**: -
- **Sample zoning**: Municipal zoning district: UNKNOWN (unmapped).
- **Recommendation statuses**: Source Cache Required
- **Queue reason**: Needs rendered ordinance section cache

### Town of Odessa

- **Code home**: https://library.municode.com/de/odessa/codes/code_of_ordinances
- **Cached sections**: 0
- **Learning status**: Municode shell reachable; ordinance content not exposed in page HTML
- **Dependency coverage**: -
- **Sample zoning**: Municipal zoning district: UNKNOWN (unmapped).
- **Recommendation statuses**: Source Cache Required
- **Queue reason**: Needs rendered ordinance section cache

### Town of Smyrna

- **Code home**: https://library.municode.com/de/smyrna/codes/code_of_ordinances
- **Cached sections**: 15
- **Learning status**: Rendered source extracted into section cache
- **Dependency coverage**: -
- **Sample zoning**: Municipal zoning district: UNKNOWN (unmapped).
- **Recommendation statuses**: Cached Code Interpreter Active, District Mapping Needed, Cached Use Answer, Cached Use Answer, Cached Use Answer, Cached Use Answer, Cached Use Answer, Cached Permission Signals
- **Queue reason**: -

### Town of Townsend

- **Code home**: https://library.municode.com/de/townsend/codes/code_of_ordinances
- **Cached sections**: 0
- **Learning status**: Municode shell reachable; ordinance content not exposed in page HTML
- **Dependency coverage**: -
- **Sample zoning**: Municipal zoning district: UNKNOWN (unmapped).
- **Recommendation statuses**: Source Cache Required
- **Queue reason**: Needs rendered ordinance section cache
