# Unincorporated New Castle County

## Authority

Primary ordinance source: New Castle County Code, Chapter 40.

Primary GIS source: New Castle County GIS REST services.

## Current PropSpector Treatment

- Determines parcel geometry and zoning through NCC GIS.
- Treats parcels outside incorporated municipalities as subject to NCC Chapter 40.
- Uses NCC use definitions and district logic to classify likely development options.
- Applies environmental protected-resource screening using mapped NCC environmental and WRPA services.
- Moderates theoretical yield using open space, protected resources, parking, fire access, site support, and shape/layout assumptions.

## Important Interpretation Themes

- Mixed use must not double count commercial GFA and apartment units.
- Commercial apartments can be limited-use rather than impossible.
- Parking and access can materially reduce buildable yield.
- Public ownership should change ranking and add a disclaimer.
- Forest calculations require classification; until classification is available, use conservative notes and the assumed tier rule already encoded.

## Calibration Parcels

| Parcel | Purpose |
| --- | --- |
| 0804930379 | Mixed-use/apartment calibration against record-plan expectations |
| 0902800058 | Public-owner and civic/custom-use ranking calibration |
| 1105400001 | Federal-owner ranking calibration |
| 1000100014 | Commercial/residential limited-use screening |
| 1000100074 | CR-style feasibility ranking calibration |

## Open Work

- Encode more limited-use standards from Chapter 40.
- Add road classification checks where limited uses require collector or higher access.
- Expand record-plan comparison set.
- Add ordinance-source snapshots so code changes can be detected.
