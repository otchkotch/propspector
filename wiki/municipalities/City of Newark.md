# City of Newark

## Status

Seed bot created.

## Current PropSpector Treatment

PropSpector now recognizes Newark as a separate municipal code ecosystem. Newark parcels should not fall back to unincorporated New Castle County yield math. The seed bot can identify the municipal profile, preserve mapped zoning context, and explain which code dependencies must be learned before a yield is trusted.

## Source Status

- Probable municipal code source: `https://ecode360.com/NE0416`
- Source requires section-level confirmation before standards are encoded.

## Required Profile Work

- Confirm the authoritative Newark zoning chapter and section anchors.
- Map Newark district codes from the NCC municipal zoning layer to official district names.
- Encode permitted, accessory, conditional, special, and prohibited uses.
- Encode bulk, density, height, lot coverage, parking, loading, open-space, landscaping, subdivision, utilities, access, and review procedure.
- Add adjoining parcel, frontage, street classification, neighborhood character, and entitlement-risk checks.
- Add calibration parcels with known Newark approvals or recorded plans.

## Design Rule

Until this profile is complete, Newark parcels should return a municipal-bot result rather than a confident county-code yield.
