# Thesis of Operation

## Thesis

PropSpector should produce a conservative, explainable feasibility opinion by combining parcel-specific GIS evidence with jurisdiction-specific code interpretation. It should not merely look up a zoning district and multiply acreage by a density number.

The app becomes trustworthy when every recommendation can answer four questions:

1. **Where is the parcel legally located?**
   The municipality or unincorporated status controls which ordinance is authoritative.

2. **What uses are legally available?**
   Use tables, definitions, limited-use rules, special-use rules, and district-specific conditions control whether the app should screen residential lots, apartments, mixed use, commercial GFA, civic/institutional options, solar, industrial, or a custom/inferred use.

3. **What physical constraints reduce theoretical yield?**
   Protected resources, open-space ratios, parking ratios, fire-lane/access needs, building footprint assumptions, parcel shape, frontage, and split zoning should moderate the code maximum.

4. **How confident is the app, and why?**
   Known parcel calibrations, recorded-plan comparisons, and ordinance source links should determine whether the result is high-confidence, review-required, or a warning-only screen.

## Operating Principles

- **Jurisdiction first**: never apply New Castle County unincorporated rules to incorporated municipalities.
- **Uses before math**: determine whether the development option is permitted, limited, special, accessory, or not contemplated before calculating yield.
- **Plain labels for humans, precise labels for code**: the UI should say `Apartments`, `Mixed Use`, or `Single-Family Lots`; the engine can preserve ordinance labels internally.
- **Conservative until calibrated**: when classification, forest tier, road class, municipal interpretation, or access is uncertain, assume the less aggressive result and disclose the assumption.
- **Constraints stack carefully**: environmental resource overlaps must not double count protected acreage. Higher-protection resources trump lower-protection resources for protected-land calculations, while the environmental resources panel may still show raw acreage.
- **Zoning distinctions may be non-bounded**: if a parcel intersects multiple zoning districts, the app must calculate whether each district materially affects the site instead of relying only on a representative point or declaring a clean parcel-wide split.
- **Development context extends beyond the parcel boundary**: neighboring parcels, frontage, legal access, and connection to a street, highway, or boulevard can control whether a theoretical yield is actually developable.
- **Entitlement risk is part of feasibility**: neighborhood character, organized opposition/support, council district politics, civic associations, historic context, and discretionary approval power can determine whether a technically plausible project is practical.
- **Public ownership matters**: public, school, federal, municipal, or sovereign ownership should lower private-development ranking and add a disclaimer.
- **Recorded plans are calibration anchors**: known record plans should be used to catch systematic over- or under-estimation.

## Expansion Thesis

Each municipality should be implemented as a profile with its own:

- zoning GIS source;
- ordinance source;
- district vocabulary;
- use taxonomy;
- dimensional standards;
- parking and open-space standards;
- overlay constraints;
- road/access conditions;
- appeal/variance/conditional-use logic;
- calibration parcels;
- known caveats.

If a municipality cannot be represented cleanly by a profile, that is evidence the architecture needs a new regulatory abstraction rather than another parcel-specific patch.

## Self-Realizing Bot Thesis

PropSpector should eventually be able to recognize when a new jurisdiction cannot be safely interpreted by the current engine. In that case, the app should not force the parcel through a mismatched profile. It should identify the missing jurisdiction, summarize the unknown code dependencies, and recommend creation of a new jurisdiction bot/profile.

A jurisdiction bot is not just a zoning parser. It is a regulatory interpreter for the legal ecosystem that controls building construction and development approval in that place.

The bot must understand that zoning chapters, subdivision rules, building codes, fire access, stormwater, parking, streets, utilities, environmental protection, historic review, public works, special districts, and discretionary approval procedures can all affect one another. No single chapter should be treated as superior without checking the related direct and indirect regulations.

Every zoning district is a first-class research target. A bot is not allowed to become parcel-trained around one successful district, one calibration parcel, or one lucrative development option. For each municipality, the bot must build a district-and-use matrix that identifies what is permitted by right, limited, special, conditional, accessory, prohibited, or undefined for every district it can discover. Residential, commercial, office, industrial, institutional, civic/public, mixed-use, waterfront, planned, overlay, conservation, and other locally named districts must all be captured. Yield math comes after that classification, not before it.

The correct municipal learning unit is not `R-5-C apartments` or any other single district result. The correct unit is the municipality's complete regulatory ecosystem: district inventory, use permissions, special or limited standards, definitions, dimensional standards, parking/loading, street access, subdivision, utilities and fees, stormwater/environmental rules, fire/building constraints, historic or overlay districts, procedure, and calibration records.

## Version Thesis

The `0.xxx` release line is the teaching and calibration phase. Each minor version should represent a clearer understanding of how to translate one jurisdiction's zoning language into a reusable interpretation model for the next jurisdiction.

The long-term goal is not simply to encode New Castle County. The goal is to develop a durable method for reading municipal and state-level code systems, identifying their common regulatory concepts, and translating those concepts into consistent feasibility logic without erasing each jurisdiction's local quirks.
