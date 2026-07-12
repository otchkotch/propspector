# Daily Regulatory Review Runbook

## Purpose

The daily review checks whether PropSpector still interprets key parcels and regulatory conditions in a defensible way. It is meant to catch drift in:

- GIS service fields or layer behavior;
- zoning district interpretation;
- limited-use and special-use handling;
- public-owner ranking;
- protected-resource calculations;
- mixed-use/apartment yield moderation;
- UI-facing recommendation language.

## Automated Review

Run:

```powershell
.\.venv\Scripts\python.exe .\tools\daily_regulatory_review.py
```

Then run the municipal self-discovery audit:

```powershell
.\.venv\Scripts\python.exe .\tools\municipal_self_discovery.py
```

The script writes a dated report to:

```text
wiki\daily-reviews\YYYY-MM-DD.md
```

The municipal audit writes:

```text
wiki\municipal-self-discovery\latest.md
cache\municipal-self-discovery\ingestion_queue.json
```

## Scheduled Task

The helper installer:

```powershell
.\tools\install_daily_regulatory_review_task.ps1
```

creates a Windows scheduled task named:

```text
PropSpector Daily Regulatory Review
```

Default schedule: daily at 7:30 AM.

## Review Standard

A daily review is considered clean when:

- all calibration parcels run without service errors;
- unincorporated parcels use New Castle County code logic;
- incorporated parcels are flagged as municipal review-required unless that municipality has a completed profile;
- every registered municipal bot is audited, not only recently tested municipalities;
- municipal bots with rendered ordinance caches produce source-backed answer cards instead of generic placeholder cards;
- municipal bots without usable rendered ordinance caches are listed in the ingestion queue for follow-up extraction;
- known mixed-use calibration parcels still produce mixed-use yields in the expected range;
- public-owner parcels do not rank civic/custom public uses above realistic private-development options without a warning;
- environmental constraints appear in the result when present;
- no recommendation uses confusing labels such as `Other / custom use` as a top result without explanation.

## When the Review Finds Something

Add an entry to [Interpretation Findings Log](Interpretation%20Findings%20Log.md) using [Finding Entry](templates/Finding%20Entry.md).
