# Personal Journal - PropSpector Direction

## 2026-06-29 - North Star

> I want this app to do cool stuff.
>
> I want a self-realizing bot generator that is particularly able to assess whether a new bot is required to interpret the zoning and development codes for a new or yet undocumented state, sovereign, municipality, county, township, town, city, village, etc. It should seek to understand how the laws and regulations of that particular subdivision of government regulates building construction. It is imperative to understand that code regulations are interdependent and sometimes dictate specificity of regulation with dozens of other chapters and they should never be considered singularly superior without confirming other related (whether directly or indirectly) regulations. 
It should determine whether a new bot is necessary and built it, name it by that particular municipality, and pursue its success in interpreting code for a nontechnical laymen. It is ideally suited to precisely analyze and subsequently visualize how certain regulations and existing factorscan affect development related to yields, investment risk, capital needed, unexpected fees, etc...

Unexpected fees are anything from connection fees required from a utility provider, cut/fill costs, road construction, etc...

The purpose of the municipal bots is to understand every nook and cranny of every borough and county and city and township and the like to assist laypeople in understanding the actual risks of investing in land development through visualizations and ai projections that are based on researched and documented data queried from reliable sources.

The gui should be well organized, attractive, modular, expandable, and operational in either web app, mobile or desktop form. Color schemes should be dark and windows should be round - very round.

If you haven't already made a Wilmington, Middletown, City of Newark, Smyrna, or any other incorporated areas in New Castle County bots that integrates into the existing propspector, do so now. We'll keep this restricted to NCC for now. However, if you find similar codes in other states, feel free to create those too.

Input parcels should be checked at least once daily to ensure the app is running as it should. 

all municipal bots are programmed to learn continuously, throughout the day without tripping bot detection until they are adequately able to cache/read and interpret code instantly. they focus on digesting zoning code above any other section of a municipal code since zoning code determines building constraints.

a learning bot should seek new, additional, or unique municipal codes for particular states through municode, or ecode360, or official zoning regulation pdf and search the net to ensure all municipalities of said state, county, township, jurisdiction, etc... have been compiled and can therefrom be easily monitored for changes in legislation or regulation. it is expected of codex, to create the correct bots for each respective municipality in a given state and to ensure that the respective bot can adequately comprehend the respective municipal regulations to accurately translate complicated regulatory code into easily digestible facts to guide the feasibility app in determining what development is permitted and feasible.

this is a stable app that can open and operate multiple instances stably.

once a municipal bot has ingest some or all portions of their respective municipal code, have them report their current status and work summary thus far. at scheduled review time, codex should read each bots notes, determine if they are falsely reporting, and correct any poor code that may be preventing them from accomplishing their respective tasks.

the unique aspects of each municipality could be novel similar alike or verbatim, but regardless of what each bot may perceive as duplicated text or code, it should not assume it comprehends it fully simply because it found matching words or phrases.

because ncc rest servers are the source of all spatial and parcel data, it categorizes other municipalities zoning districts as their respective hundred number next to the applicable zoning district. for instance, if NCC GIS returns a zoning of 26R-3, this relates specifically to City of Wilmington since Wilmington's hundred is 26. So for better interpretation of the municipal codes, bots should drop the number preceding the zoning district. In this particular example case, the actual City of Wilmington Zoning District is R-3, not 26R-3.

when codex is running its review, the last step before finalizing should be check at least one parcel in each respective municipality to ensure municipal code bots are properly inputting/translating their code for use in determining feasibility of that municipalities particular development options. in some municipalities, certain development options may have unique names and should be treated as such. each municipality is independent and governed by their own regulations.


## Working Interpretation

PropSpector should eventually become more than a parcel screen. It should become a regulatory interpretation system that can decide when a jurisdiction is understood well enough to calculate, and when the app needs to generate or request a new jurisdiction-specific interpreter.

The app should treat a new municipality, county, township, state, sovereign, or other regulatory body as a new legal ecosystem until proven otherwise.

## Product Direction

- The app should recognize when an existing profile is insufficient.
- The app should identify what kind of interpreter is needed for a new jurisdiction.
- The app should map code dependencies before calculating yield.
- The app should distinguish black-letter code, cross-referenced standards, administrative interpretation, political/entitlement risk, and physical site constraints.
- The app should avoid pretending one zoning chapter is the whole answer.
- The app should treat building construction regulation as interdependent: zoning, subdivision, building, fire, stormwater, parking, environmental, historic, utilities, streets/access, public works, and special districts may all matter.

## Bot Generator Thesis

A jurisdiction bot should be generated only after PropSpector can answer:

1. What government subdivision controls the parcel?
2. What code sources are authoritative?
3. What code chapters regulate building, site design, use, access, density, dimensional standards, environmental protection, parking, utilities, and approval procedure?
4. Which chapters cross-reference or override each other?
5. Which standards are objective and calculable?
6. Which standards require discretion, interpretation, hearings, politics, or agency coordination?
7. Which facts must be gathered from GIS, recorded plans, neighboring parcels, street classification, public ownership, or physical access?
8. Which existing PropSpector interpreter can be reused?
9. Which parts require a new profile, new parser, or new review workflow?

## Rule

No chapter is singularly superior until related code sections are checked. A zoning result should be treated as provisional until the app has considered direct and indirect dependencies that can change the development answer.
