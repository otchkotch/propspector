# Town of Smyrna

## Status

Seed bot created.

## Current PropSpector Treatment

PropSpector now recognizes Smyrna as a separate municipal code ecosystem. Smyrna parcels should not fall back to any county yield math unless the controlling jurisdiction is explicitly confirmed. The seed bot can identify the municipal profile, preserve mapped zoning context, and explain which code dependencies must be learned before a yield is trusted.

## Source Status

- Municipal code source: `https://library.municode.com/de/smyrna/codes/code_of_ordinances`
- Municode home is reachable, but section-level zoning/use/dimensional anchors are not yet encoded.

## Required Profile Work

- Confirm the authoritative Smyrna zoning chapter and section anchors.
- Confirm whether a parcel also requires Kent County or other external jurisdiction context.
- Map Smyrna district codes to official district names.
- Encode permitted, accessory, conditional, special, and prohibited uses.
- Encode bulk, density, height, lot coverage, parking, loading, open-space, landscaping, subdivision, utilities, access, and review procedure.
- Add adjoining parcel, frontage, street classification, neighborhood character, and entitlement-risk checks.
- Add calibration parcels with known Smyrna approvals or recorded plans.

## Design Rule

Until this profile is complete, Smyrna parcels should return a municipal-bot result rather than a confident county-code yield.
