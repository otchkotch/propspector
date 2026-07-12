# City of Wilmington

## Status

Seed bot active.

## Current PropSpector Treatment

PropSpector now routes Wilmington parcels into a Wilmington-specific seed profile instead of applying unincorporated New Castle County zoning logic. The profile resolves address/parcel input, detects City of Wilmington jurisdiction, identifies municipal zoning districts from the NCC municipal zoning layer, and reports when a non-bounded zoning distinction is present.

The seed bot intentionally withholds yield recommendations until Wilmington-specific permitted-use, dimensional, parking, access, subdivision, utilities, fee, fire-access, neighborhood-character, and entitlement-risk dependencies are encoded.

## Required Profile Work

- Expand authoritative Wilmington ordinance source mapping beyond the current Chapter 48 seed anchors.
- Continue measuring municipal zoning intersections by parcel geometry, not only representative point, because 1021 Gilpin Avenue / parcel 2602130233 returns both `R-3` and `R-5-C` context after stripping the NCC GIS `26` prefix; the measurable parcel-area overlap is `R-5-C`.
- Treat this as a non-bounded zoning distinction: the contact must be tested for materiality before the app applies one district or declares a clean split.
- Maintain district code translations for known Wilmington GIS codes such as `26R3` and `26R5C`, displaying them to users as `R-3` and `R-5-C`.
- Encode permitted, conditional, accessory, and prohibited uses.
- Encode bulk, density, height, lot coverage, parking, loading, open-space, and overlay standards.
- Add adjoining parcel, access, street classification, neighborhood character, and political/entitlement risk context.
- Add calibration parcels with known approvals or recorded plans.

## Design Rule

Until this profile is complete, Wilmington parcels should return a municipal-code-review result rather than a confident county-code yield.

## Seed Profile Notes

- `R-3`: One-family row houses.
- `R-5-C`: Apartment houses, high density.
- 1021 Gilpin Avenue resolves to parcel `2602130233`.
- For 1021 Gilpin Avenue, the bot marks the zoning moment as important because the parcel has a non-bounded zoning distinction: `R-5-C` produces measurable parcel-area coverage, while `R-3` appears as municipal zoning contact/intersection context that must be interpreted before any yield can be trusted.
- App version `0.1.11` presents Wilmington review as user-facing development options: Apartments, Rowhouse / One-Family, Commercial or Institutional, and Custom / Emerging Use. It does not display internal bot names as development-option cards.
