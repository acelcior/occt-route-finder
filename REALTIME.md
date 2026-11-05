# Real-time bus positions: findings and plan (not built)

## What exists

- OCCT's live tracker is **ETA Transit** at https://binghamtonupublic.etaspot.net/
  (accessible version: https://binghamtonumobile.etaspot.net/index.php?text=1).
  It shows vehicles, next stops and stop arrival predictions, and it is linked from
  every OCCT route page ("use ETA Transit for real-time arrivals").
- OCCT's September 22, 2026 rider notice says ETA shows *arrival* times only: for trips
  starting at UDC, Mohawk or the Union, riders should use the scheduled departure times
  on the website — which is what this planner already does.
- **No public API, GTFS or GTFS-realtime feed is documented** on occtransport.org or on
  the ETA SPOT site, and there are no terms of use for programmatic access. ETA SPOT
  deployments are known to have an internal JSON endpoint used by their own web app,
  but it is undocumented and unlicensed for third parties, so this project does not call it.

## Plan, if OCCT agrees

1. Ask OCCT (contact page) / ETA Transit for either a **GTFS-realtime** feed or written
   permission plus documentation for the ETA SPOT endpoint. GTFS-RT is the standard and
   lets the same data flow into Google/Apple Maps and Transit app.
2. Export our static dataset as GTFS (`stops.txt`, `routes.txt`, `trips.txt`,
   `stop_times.txt`, `calendar.txt`/`calendar_dates.txt` map 1:1 onto
   `data/occt_dataset.*.json` + `data/service_calendar.json`) so trip ids can be matched
   to real-time `TripUpdate`s.
3. In the API, overlay predictions on the `ride` legs: `board.realtime`, `delay_min`,
   and a `vehicle` field; keep the scheduled time visible when no prediction exists.
   Cache the feed for ~15 s per serverless instance.
4. Frontend: show "live" badges and a "last updated" stamp; fall back silently to the
   schedule when the feed is down.

## Why not now

Scraping an undocumented endpoint would break without notice and may violate the vendor's
terms; the schedule-based planner already gives correct departure times for the key
origin stops (Union, UDC, Mohawk), which is exactly what OCCT tells riders to use.
