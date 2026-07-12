# PropSpector Project Wiki

This wiki tracks how PropSpector interprets local land-use regulation, how those interpretations are tested, and what must change as the app expands into additional municipalities.

## Working Thesis

PropSpector should be treated as a jurisdiction-aware regulatory interpreter, not a static zoning calculator. The app should separate five concerns:

1. **GIS facts**: parcel geometry, zoning district, municipality, road context, environmental constraints, ownership, and recorded-plan clues.
2. **Ordinance facts**: permitted uses, limited/special-use rules, bulk and density standards, open-space rules, parking rules, and overlays.
3. **Interpretation rules**: how ordinance text maps to a development option, when a use is by-right versus review-required, and when conservative assumptions are required.
4. **Yield modeling**: how dimensional, environmental, parking, fire access, market, and shape constraints reduce theoretical yield into a planning-level recommendation.
5. **Calibration evidence**: known parcels and recorded plans used to detect when the app is overconfident, too conservative, or misclassifying a use.

The app should keep these concerns visible and testable so new municipalities can be added by profile, not by one-off patches.

## Core Pages

- [Thesis of Operation](Thesis%20of%20Operation.md)
- [Personal Journal - PropSpector Direction](Personal%20Journal%20-%20PropSpector%20Direction.md)
- [Daily Regulatory Review Runbook](Daily%20Regulatory%20Review%20Runbook.md)
- [Jurisdiction Expansion Matrix](Jurisdiction%20Expansion%20Matrix.md)
- [Interpretation Findings Log](Interpretation%20Findings%20Log.md)
- [PropSpector Update Model](PropSpector%20Update%20Model.md)
- [Regulatory Interpreter Architecture](engineering/Regulatory%20Interpreter%20Architecture.md)

## Municipality Profiles

- [Unincorporated New Castle County](municipalities/Unincorporated%20New%20Castle%20County.md)
- [City of Wilmington](municipalities/City%20of%20Wilmington.md)
- [City of Newark](municipalities/City%20of%20Newark.md)
- [Town of Middletown](municipalities/Town%20of%20Middletown.md)
- [Town of Smyrna](municipalities/Town%20of%20Smyrna.md)

## Daily Review Output

Daily generated reports are written to [daily-reviews](daily-reviews/).

## North Star Reviews

Strategic reviews tied to the personal journal are written to [north-star-reviews](north-star-reviews/).
