# Regulatory Interpreter Architecture

## Desired Shape

PropSpector should evolve toward a profile-driven regulatory interpreter:

```text
Parcel GIS facts
  -> Jurisdiction resolver
  -> Jurisdiction sufficiency check
  -> Bot/profile generator recommendation
  -> Jurisdiction profile
  -> Adjoining parcel and access context
  -> Neighborhood character and entitlement risk screen
  -> Use classifier
  -> Ordinance permission checker
  -> Dimensional and environmental capacity model
  -> Market/value screen
  -> Recommendation ranker
  -> UI/report evidence trail
```

## Profile Boundary

A jurisdiction profile should own:

- source URLs and code identifiers;
- district aliases;
- use taxonomy;
- permitted/limited/special use tables;
- dimensional standards;
- parking and loading standards;
- open-space and environmental standards;
- overlay rules;
- road/access prerequisites;
- warnings and assumptions;
- calibration parcels.

## Bot/Profile Generator

Before applying a profile, PropSpector should decide whether the profile is sufficient for the jurisdiction and proposed development question.

The generator should classify missing work:

- new jurisdiction profile required;
- existing profile can be extended;
- new ordinance parser required;
- new GIS source mapping required;
- new cross-chapter dependency map required;
- human legal/planning review required before automation.

The generator should be conservative. If the controlling government subdivision is unknown, or if the app has not mapped the relevant interdependent regulations, it should stop short of a confident yield and explain what bot/profile must be created next.

## Engine Boundary

The shared engine should own:

- parcel geometry handling;
- adjoining parcel detection;
- street/highway/boulevard access and frontage classification;
- area and overlap calculations;
- resource trumping;
- recommendation ranking;
- entitlement-risk scoring;
- market screening;
- report formatting;
- validation and regression tests.

## Refactor Trigger

If adding a municipality requires changing core yield math for a municipality-specific exception, first ask whether the rule belongs in a profile. Core engine changes should be reserved for concepts that apply across jurisdictions.

## Access And Adjoining Parcel Requirement

Every development interpretation should eventually include:

- all adjoining parcels touching or functionally affecting the subject parcel;
- public street, highway, boulevard, alley, or private-access frontage;
- whether access appears legal and practical for the proposed use intensity;
- whether neighboring parcel ownership suggests assemblage potential;
- whether adjacent zoning or uses constrain transition, buffering, density, or access;
- whether a parcel is landlocked or dependent on easement/access rights not visible from basic zoning.

This should become a shared context service used by county and municipal profiles.

## Neighborhood Character And Political Power Requirement

For municipal interpretation, especially Wilmington, a feasibility result should eventually identify entitlement risk separately from code math.

Signals to consider:

- surrounding land use and building pattern;
- zoning transition at parcel edges;
- nearby civic associations or neighborhood planning areas;
- historic district or neighborhood conservation district context;
- discretionary approvals requiring zoning board, planning commission, or council action;
- whether the proposed use changes neighborhood intensity, parking pressure, traffic, height, or perceived character;
- prior nearby approvals or denials if available;
- council district or political-review path where public approval is required.

The app should not pretend political risk is law. It should label it as entitlement risk and explain why it changes feasibility confidence.
