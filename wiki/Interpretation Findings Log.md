# Interpretation Findings Log

This page records interpretation findings, calibration lessons, and architecture decisions for PropSpector.

### 2026-06-30 - Middletown official PDF zoning source and bundled cache

- **Parcel**: 2302500083 / 650 Middletown Odessa Road, Middletown
- **Finding**: Middletown zoning is not reliably available through the prior Municode assumption. The official zoning source for this profile is the town-hosted PDF zoning code at `https://evogov.s3.us-west-2.amazonaws.com/126/media/302288.pdf`.
- **Decision**: Add a PDF extractor path to the municipal cache builder, extract Middletown into 31 cached zoning sections, preserve stronger caches when broad discovery returns weaker results, and bundle municipal section/status caches into packaged PropSpector releases.
- **Status**: Implemented in app version `0.1.22`.

### 2026-06-30 - Full municipal cache sweep

- **Finding**: A full NCC municipal registry cache run produced source-backed caches for Clayton, Delaware City, Wilmington, Newark, Middletown, and Smyrna. Arden, Ardencroft, Ardentown, Bellefonte, Elsmere, New Castle, Newport, and Odessa resolved to invalid Municode state landings through the current registry URLs. Townsend loaded but yielded no usable rendered sections.
- **Decision**: Treat failed/empty municipal sources as a source-discovery problem, not an interpreter answer. Keep them queued for alternate official source discovery and do not generate fake feasibility cards. Preserve stronger existing caches when a later broad extraction produces fewer usable sections.
- **Status**: Logged in `wiki/municipal-self-discovery/latest.md`; packaged cache bundle updated in app version `0.1.22`.

## Seed Findings

### 2026-06-29 - Mixed-use calibration parcel

- **Parcel**: 0804930379
- **Finding**: Mixed-use output must remain available for this parcel. Prior review showed an expected reading near 174 apartments and roughly 25,000 sf commercial GFA.
- **Decision**: Limited-use or review-required options with positive calculated yield should display their yield and income instead of being reduced to `Likely not feasible`.
- **Status**: Implemented in UI card logic.

### 2026-06-29 - Public-owner ranking

- **Parcels**: 0902800058, 1105400001
- **Finding**: Public, school, municipal, state, federal, or sovereign ownership should affect private-development ranking. Civic or institutional options may be legally possible but are often not realistic for private-developer feasibility.
- **Decision**: Detect public ownership and rank civic/custom public-use buckets lower, with a clear disclaimer.
- **Status**: Implemented for additional federal-owner labels.

### 2026-06-29 - Environmental acreage display

- **Finding**: The environmental resources panel should show raw resource acreage when a resource exists, while yield math should preserve trumping rules for protected-resource calculations.
- **Decision**: Keep UI presence acreage separate from protected-resource capacity math.
- **Status**: Implemented.

### 2026-06-29 - Wilmington non-bounded zoning distinction

- **Parcel**: 2602130233 / 1021 Gilpin Avenue, Wilmington
- **Finding**: Address lookup resolves cleanly to parcel 2602130233, but full-parcel municipal zoning intersection returns both 26R3 and 26R5C. The current representative-point zoning check returns 26R5C only.
- **Why it matters**: This is a non-bounded distinction. The zoning distinction is real, but it should not be collapsed into a single parcel-wide label or treated as a clean bounded parcel split without further spatial interpretation.
- **Decision**: Treat municipal zoning overlap as an explicit interpretation issue. Future municipal profiles should calculate zoning-by-area percentages, identify the likely buildable/development portion, and decide whether the secondary district is material, transitional, or a map-boundary artifact.
- **Status**: Logged as a priority architecture requirement before Wilmington yield logic is trusted.

### 2026-06-29 - Adjoining parcels and street access are feasibility facts

- **Finding**: Parcel yield cannot be interpreted from parcel zoning alone. Neighboring parcels and access to a street, highway, boulevard, or equivalent legal frontage can control whether the parcel can actually support the theoretical development option.
- **Why it matters**: Some uses require specific road classifications, public frontage, safe ingress/egress, buffering, transition from neighboring residential districts, or assemblage with adjoining ownership. These facts are outside the zoning district label but inside the feasibility decision.
- **Decision**: Add adjoining parcel detection and street/access classification as shared regulatory context services. These should feed all municipal profiles, not just New Castle County.
- **Status**: Architecture requirement logged; not yet implemented.

### 2026-06-29 - Neighborhood character and political power affect feasibility

- **Finding**: A yield can be mathematically and legally plausible but still weak as a recommendation if neighborhood character, civic pressure, or discretionary political approval makes the entitlement path unlikely.
- **Why it matters**: Municipal code often gives boards, commissions, council, or neighborhood processes power over practical outcomes. A feasibility app that ignores that risk may overstate development potential.
- **Decision**: Track entitlement risk as a distinct layer from zoning permission and dimensional yield. It should inform ranking and confidence, but should be labeled separately so the app does not confuse political feasibility with black-letter code.
- **Status**: Architecture requirement logged; not yet implemented.

### 2026-06-29 - North Star review: jurisdictional self-awareness is the next threshold

- **Finding**: PropSpector performs useful NCC screening and now resolves address input, but it does not yet enforce a structured jurisdiction sufficiency check or generate a jurisdiction bot/profile recommendation.
- **Why it matters**: The personal journal defines the goal as a self-realizing bot generator that understands when a new legal ecosystem is present. The current app stops at municipal review, but it does not yet explain the missing bot architecture in operational terms.
- **Decision**: Prioritize a jurisdiction/profile status layer, adjoining parcel and access context, Wilmington non-bounded zoning materiality testing, and code dependency maps before expanding yield claims in new municipalities.
- **Status**: North Star review created in `wiki/north-star-reviews/2026-06-29.md`.

### 2026-06-29 - Wilmington seed bot created

- **Parcel**: 2602130233 / 1021 Gilpin Avenue, Wilmington
- **Finding**: Wilmington needs its own jurisdiction bot because Chapter 48 zoning interpretation depends on district rules, dimensional standards, parking, access, subdivision, building/fire constraints, utilities, fees, adjoining parcel context, neighborhood character, and political feasibility.
- **Decision**: Add a City of Wilmington seed profile that routes Wilmington parcels away from the New Castle County yield engine. The bot resolves jurisdiction, translates known Wilmington districts, detects non-bounded zoning contact, and withholds yield until the Wilmington dependency map is encoded.
- **Status**: Implemented in app version `0.1.2`.

### 2026-06-29 - Multi-municipality seed bot registry created

- **Finding**: The personal journal authorized more than a Wilmington bot. PropSpector needs a registry of municipality interpreters so the app can recognize when Newark, Middletown, Smyrna, or another jurisdiction requires its own legal ecosystem.
- **Decision**: Add a municipal bot registry with active seed profiles for Wilmington, Newark, Middletown, and Smyrna, plus a generic seed-bot-required fallback for other incorporated municipalities. All incorporated parcels now route through the municipal bot layer instead of the NCC yield engine.
- **Status**: Implemented in app version `0.1.3`.

### 2026-06-29 - NCC municipal discovery and continuous learning engine created

- **Finding**: The journal requires more than seed profiles. Municipal bots must learn continuously, discover municipal codes through reliable sources, cache code-source status, and report all bot results even when parcel calibration does not include every municipality.
- **Decision**: Add municipal code discovery for all NCC municipality names returned by NCC GIS, register all 15 NCC incorporated municipalities as seed bots, cache source checks, install scheduled discovery and learning tasks, and expose all bot statuses in the daily journal report.
- **Status**: Implemented in app version `0.1.4`.

### 2026-06-30 - Zoning service outage fallback and activity heartbeat

- **Finding**: `1021 Gilpin Avenue` could populate environmental preview data while Development Options appeared hung because the NCC zoning service returned `Unable to complete operation`.
- **Decision**: Municipal parcels now fall back to the jurisdiction bot profile when the municipal zoning layer is unavailable. County zoning lookup failures now produce a visible review-required result instead of crashing the zoning worker. The UI now shows an animated activity state and a clear zoning failure card.
- **Status**: Implemented in app version `0.1.5`.

### 2026-06-30 - Cancel/reset workflow and municipal bot card language

- **Finding**: The app could feel stuck after a run because there was no user-facing cancel action, stale worker results could still arrive after a user wanted to move on, and municipal bot/profile results were displayed as `Likely not feasible`.
- **Decision**: Make the Run button become Cancel during active work, invalidate stale worker results when canceled or when a new run starts, and render municipal/profile recommendations as code-review guidance instead of feasibility failures.
- **Status**: Implemented in app version `0.1.6`.

### 2026-06-30 - Municipal profile labels cleaned for users

- **Finding**: Wilmington review cards leaked internal labels such as `City of Wilmington Bot` and `Bot Generator` into Development Options.
- **Decision**: Keep the municipal interpretation machinery internal and present user-facing cards as municipal development potential, residential/mixed residential, commercial/institutional, and special/emerging uses.
- **Status**: Implemented in app version `0.1.7`.

### 2026-06-30 - Municipal learning cache truthfulness

- **Finding**: The municipal learning bots could confirm Municode source shells, but the ordinance section text was not present in the returned HTML and the structured Municode API probes returned unauthorized responses.
- **Decision**: Treat shell reachability as source discovery, not code digestion. The learning cache now records dependency-section candidates only when actual sections are extracted, and PropSpector surfaces the bot learning cache in municipal review details.
- **Status**: Implemented in app version `0.1.8`.

### 2026-06-30 - Zoning service availability is a blocker

- **Finding**: The daily review resolved parcel facts, but zoning districts returned empty for all calibration parcels in this run.
- **Decision**: Keep parcel runs review-required when zoning is unavailable and prioritize a secondary zoning fallback before trusting development-option cards during service outages.
- **Status**: Logged for follow-up after app version `0.1.8`.

### 2026-06-30 - Water Resources environmental layer expansion

- **Finding**: PropSpector exposed the core Environmental MapServer resources, but it did not expose the separate NCC WRPA MapServer layers requested for wellhead protection, Cockeysville formations, Cockeysville drainage basin, recharge areas, reservoir watersheds, WRPA floodplains, and WRPA erosion-prone soils.
- **Decision**: Make environmental resources service-aware so preview toggles, presence checks, raw acreage chips, and PDF exports can combine layers from both `BaseMaps/Environmental` and `BaseMaps/WRPA`. Add an `Erosion Prone Soils Slopes` map group and a `Water Resources` map group.
- **Status**: Implemented in app version `0.1.9`.

### 2026-06-30 - NCC zoning sublayer fallback

- **Finding**: The aggregate NCC zoning query layer returned `Unable to complete operation`, causing calibration parcels to resolve parcel facts but lose development-option yield cards.
- **Decision**: Add a fallback that probes individual NCC zoning sublayers by representative point when the aggregate zoning layer fails or returns no district. The preview facts and feasibility engine both use this fallback.
- **Status**: Implemented in app version `0.1.9`.

### 2026-06-30 - Municipal zoning code normalization

- **Finding**: NCC GIS prefixes municipal zoning codes with the municipality/hundred number, such as `26R3` and `26R5C` for Wilmington. Those are GIS transport labels, not the legal district labels users expect.
- **Decision**: Normalize municipal zoning codes before they reach municipal bots or the UI. Wilmington examples now display as `R-3` and `R-5-C`. The municipal zoning query now uses the `BaseMaps/NCC_Zoning` municipal zoning layer and retries transient ArcGIS `Unable to complete operation` responses.
- **Status**: Implemented in app version `0.1.10`.

### 2026-06-30 - Wilmington municipal cards must be useful without false yield math

- **Finding**: `1021 Gilpin Avenue` resolved to the correct parcel and environmental resources, but the Wilmington seed profile still produced placeholder-style Development Option cards and the UI treated nonnumeric municipal guidance as likely infeasible.
- **Decision**: Keep Wilmington yield math withheld until the city standards are encoded, but expose district-aware municipal review cards. `R-5-C` now produces an Apartments review card, `R-3` produces a Rowhouse / One-Family context card, and commercial/custom uses route to use-translation review instead of internal bot labels.
- **Status**: Implemented in app version `0.1.11`.

### 2026-06-30 - Aerial-first preview and overlap-only split-zoning scenarios

- **Finding**: On an office machine, `2701 Capitol Trl` felt blank because PropSpector waited for environmental resource checks before showing the aerial preview. The same parcel also revealed that split-zoning assumptions must only compare districts that actually overlap the parcel geometry.
- **Decision**: Render and publish the aerial, parcel outline, and frontage-road labels first, then load environmental and WRPA overlays afterward. County zoning lookup now queries parcel-geometry intersections before point fallback. Split-zoning scenario cards compare only overlapping mapped districts and screen two assumptions: restrictive rezoning and upside rezoning.
- **Status**: Implemented in app version `0.1.12`.

### 2026-06-30 - Wilmington rendered-section learning and preliminary R-5-C yield

- **Finding**: The Wilmington bot had enough jurisdiction/zoning context to identify `R-5-C`, but it was still withholding yield because the learner only saw the Municode shell. A normal rendered public page can expose section chunks for targeted section searches.
- **Decision**: Add a reusable rendered-section extractor for municipal Municode pages and teach the municipal learner to consume cached rendered sections. Encode a first Wilmington `R-5-C` apartment screen using Sec. 48-139, Sec. 48-151, Sec. 48-152, Sec. 48-153, and Sec. 48-443. The first screen uses FAR 6.0, no prescribed R-5-C height cap, one parking space per two families, a 70% high-rise program factor, and a 950 sf average gross unit size.
- **Status**: Implemented in app version `0.1.13`.

### 2026-06-30 - Municipal bots must learn complete district/use ecosystems

- **Finding**: The first successful Wilmington encoding overemphasized `R-5-C` because it was tied to the active calibration parcel. That is useful as a proof of extraction and yield plumbing, but it is not a sufficient municipal bot.
- **Decision**: Treat every zoning district as a first-class research target. Each municipal bot must capture residential, commercial, office, industrial, institutional, civic/public, mixed-use, waterfront, planned, overlay, conservation, and other locally named district families. The learner now tracks district inventory, commercial/institutional district language, use permissions, limited/special/conditional use standards, definitions, bulk, parking/loading, access, subdivision, utilities/fees, stormwater/environmental, fire/building, historic/overlay, procedure, and calibration-record signals before any profile should be considered mature.
- **Status**: Implemented after app version `0.1.13`; next shared build should carry this doctrine forward.

### 2026-06-30 - Wilmington district recognition refined into prospecting screens

- **Finding**: The Wilmington cache included residential, commercial, industrial, and waterfront district sections, but the app only produced useful data for the original R-5-C apartment case and generic review cards for most other district families.
- **Decision**: Add Wilmington registry entries for R-1, R-2, R-2-A, R-4, R-5-A, R-5-A-1, and R-5-B; normalize GIS labels such as `26C4`, `26M1`, `26W2`, and `26R5A1`; add FAR-based apartment screens for R-5-A, R-5-A-1, and R-5-B; and add conservative preliminary GFA/income screens for C-1 through C-5, M-1/M-2, and W-1/W-2. These screens are prospecting envelopes, not final code maximums.
- **Status**: Implemented in app version `0.1.15`.

### 2026-06-30 - Cached Wilmington use sections translated into answer cards

- **Finding**: The UI still displayed generic cards saying commercial, institutional, civic, and custom uses needed classification even though the cached Wilmington sections already answered many of those questions.
- **Decision**: Translate cached district text into use-answer cards for all learned Wilmington district families. R-5-C/R-5-B now expose institutional/civic, support commercial, and custom-use translator answers. R-3 exposes narrow corner commercial/professional and inherited school/worship/civic paths. C-1 through C-5, M-1/M-2, and W-1/W-2 now expose commercial, industrial, waterfront, board-review, and custom/emerging-use translator answers rather than falling back to generic unknowns.
- **Status**: Implemented in app version `0.1.16`.

### 2026-06-30 - Cache-backed interpretation became the default municipal bot behavior

- **Finding**: Wilmington had a specialized cached-code interpreter, but other municipal bots could still produce generic placeholder cards even when rendered code sections were cached.
- **Decision**: Move cache-backed interpretation into the base municipal bot path. Every municipal bot now checks its rendered section cache, detects mapped district signals, reports matched district sections where possible, emits cached use-family answer cards, summarizes permission-path signals, and clearly identifies remaining implementation work. If a municipality has no usable rendered section cache, the bot says source cache is required rather than pretending the local code is understood. The Municode extractor now reads the municipal bot registry so every registered Municode-backed bot can use the same ingestion pipeline.
- **Status**: Implemented in app version `0.1.17`.

### 2026-06-30 - Municipal self-discovery audit added

- **Finding**: PropSpector was still operationally biased toward the municipalities actively tested in conversation, especially Wilmington, Newark, and Middletown. The journal requires all municipal bots, including quieter or not-yet-mentioned jurisdictions, to keep seeking source material and proving whether they can answer from cached code.
- **Decision**: Add a municipal self-discovery audit that checks every registered municipal bot, counts rendered ordinance sections, runs a sample interpretation, records whether source-backed cards are produced, and writes an ingestion queue for bots that still need rendered code extraction. The daily review runbook now requires this audit so placeholder cards become a tracked failure mode rather than an acceptable fallback.
- **Status**: Implemented in app version `0.1.18`.

### 2026-06-30 - Wilmington C-2 inheritance calibration

- **Parcel**: 2602010008 / 2000 Pennsylvania Avenue, Wilmington
- **Finding**: PropSpector correctly resolved the parcel as C-2 / Wilmington, but it treated the district as only a secondary commercial GFA screen. Wilmington Sec. 48-193(c)(1) permits uses allowed in R-5-C and C-1, so C-2 parcels need apartment and mixed-use prospecting screens before generic commercial GFA is ranked.
- **Decision**: Add C-2 inherited R-5-C apartment and C-1/R-5-C mixed-use screens, sort Wilmington development options by estimated upside, and add 2000 Pennsylvania Avenue as a daily calibration parcel.
- **Status**: Implemented in app version `0.1.19`.

### 2026-06-30 - New parcel input cancels stale research

- **Finding**: After one parcel run, a user could enter a new parcel while a stale or long-running worker still held the app in a running state. The main button still behaved as a plain cancel button, forcing an extra click and making the app feel stuck.
- **Decision**: Track the active parcel/intended-use/map-group signature. If the user changes that input while work is active, the main button becomes `Run New Search` and automatically invalidates the stale run before starting the new query.
- **Status**: Implemented in app version `0.1.20`.

### 2026-06-30 - Development options no longer show translator-note cards

- **Finding**: Wilmington commercial parcels could display long municipal code translator notes as oversized Development Option cards. This cluttered the result list, clipped text in the UI, and made the app look like it was failing even when valid yield cards existed.
- **Decision**: Treat translator/use-answer notes as fallback guidance only when no screened yield cards exist. When real development options are available, the app now shows the yielded options only.
- **Status**: Implemented in app version `0.1.21`.
