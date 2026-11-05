# One-shot build prompt for Fable — OCCT Route Finder

Paste everything below the line into a Fable (claude-fable-5-1) Claude Code session opened at the repo root.

---

You are taking the **OCCT Route Finder** (Binghamton University's Off Campus College Transport bus system) from a single-route, "next bus today" demo to a production-quality trip planner that stays correct across the whole academic year. Work autonomously in this repo until every acceptance criterion below passes. Read the code before changing it; extend what exists rather than rewriting it.

## 1. What already exists (read these first)

- `src/api/index.py`: FastAPI on Vercel (`vercel.json`). `POST /api/route {origin, destination}`, `GET /api/stops`, `GET /api/health`. It geocodes (stop-name snap → Google if `GOOGLE_API_KEY` → Nominatim), takes the **nearest stop on each route** to each pin, keeps routes where the destination index is after the origin index, finds the next departure today (plus tomorrow's `after_midnight` trips), interpolates times between timepoints (`_dense_stop_times`), and ranks by walking distance. **It has uncommitted changes** (midnight carry, `trips_for_date`, per-trip `days`). Keep that intent.
- `src/stop_names.py`: stop-name normalization and coordinate lookup.
- `public/` (`index.html`, `app.js`, `style.css`): vanilla JS frontend with a theme toggle, stop autocomplete, and only From/To inputs.
- Data:
  - `data/occt_routes_geo.json`: **live** legacy format (22 route-direction entries, weekday/weekend buckets, `stop_coords` inline). The API reads this.
  - `data/occt_dataset.fall2026.candidate.json`: **new normalized** format from `scripts/build_dataset.py`: `meta`, `stops{id:{name,lat,lon}}`, `lines[{id,name,url,directions{key:{headsign,tier,stops}}, trips[{direction,tier,days,after_midnight?,note?,times[{seq,stop,time}]}]}]`. **Nothing reads it yet.**
  - `data/occt_routes_geo.fall2026.candidate.json`: legacy-format candidate from `scripts/parse_schedules.py`.
  - `data/raw/fall2026/*.html`: committed raw snapshots from `scripts/scrape_schedules.py`.
  - `data/stop_cache.json`: stop-name → coordinates, with aliases.
- Pipeline: `scrape_schedules.py` (snapshot) → `build_dataset.py` (parse, validate, `--strict`) → candidate → human review → promote. Dev-only dependencies are in `requirements-dev.txt`; runtime dependencies in `requirements.txt` must stay minimal for Vercel.

## 2. Known defects to fix (verify each one yourself, then fix the root cause)

1. **Timezone.** `datetime.now()` is naive, and Vercel runs in UTC, so "next bus" is likely off by 4–5 hours. Use `zoneinfo.ZoneInfo("America/New_York")` everywhere. Handle DST correctly (it ended 2026-11-01; it starts again 2027-03-14).
2. **Service day vs. calendar day.** Late Nite and Downtown Express trips after midnight belong to the *previous night's* service ("Fri & Sat nights"; they are currently encoded as `days:["Sat","Sun"]` + `after_midnight`). If Friday has no service, the 12:45 AM Saturday run must disappear too. Model trips GTFS-style: `service_day` + times that can exceed 24:00 (e.g. `24:45`). Do not use calendar-date guessing.
3. **Loops and repeated stops.** `stops.index()` returns the first occurrence, and `dest_idx <= origin_idx` rejects valid trips on loop lines (Campus Shuttle, Oakdale Commons, Vestal Shopping, ITC–UClub), where origin == terminus or a stop appears twice. Use stop sequence (`seq`), not name lookup.
4. **Nearest-stop-only selection.** Choosing the single closest stop per route misses better boardings, for example one 150 m further away whose bus arrives 20 min earlier. Consider every stop within a walking radius.
5. **Ranking.** It currently sorts by walk distance first, which is wrong for a trip planner. Rank by **arrival time**, then fewer transfers, then less walking. Return several departures, not just the earliest one per route.
6. **No transfers.** Add one- and two-transfer journeys (for example Downtown Southside → UDC → Westside), with a minimum transfer time and walking transfers between nearby stops.
7. **Stop identity.** The same physical stop has several IDs (`court_and_hawley_streets` / `hawley_and_court_streets`, `state_and_hawley_sts` / `downtown_state_and_hawley`, `univ_union` / `university_union`, `uclub_univ_plaza` / `uclub_university_plaza_bus_shelter`, `campus`). Normalization also produced `street_charles_street` ("St Charles" was expanded as Street instead of Saint). Build a canonical stop table with an alias map. Transfers depend on it.
8. **21 stops missing coordinates** (listed in `meta.stops_missing_coords`). Resolve them through aliases to known stops or from `stop_cache.json`. Never invent coordinates. Leave any that can't be resolved in a `TODO_COORDS` report, excluded from geographic snapping but still usable when picked by name.
9. **Downtown Express** has two routing variants per night (`de-fri-a/b`, `de-sat-a/b`, "UClub first" vs "Downtown first"), placeholder stops like `campus`, and appears twice in the legacy file under the same name. Give it distinct, readable variant names.
10. **Per-trip qualifiers.** "Skips Acad A" / "No Acad A" mean the trip **does not stop** at Hinman/Academic A, so don't offer a boarding or alighting there. Also handle "Sat only", "Sun only", "No Fri", "Skips Union", and "No Inner Loop service on evenings, weekends, or holidays" (Campus Shuttle). Each must be machine-readable, not just a `note`.
11. **Interpolated times are estimates.** Only timepoint columns are published. Mark each time `scheduled` or `estimated` in the API, and show estimated times as "~5:42 PM" in the UI.

## 3. Service calendar (the biggest gap; OCCT changes service all year)

Add `data/service_calendar.json` (GTFS `calendar` + `calendar_dates` semantics) that maps every date to one service profile:

- `regular` (Fall/Spring semester), `interim` (only the ITC–Campus Shuttle `ics` runs, weekdays 8 AM–6 PM, and regular service is paused), `summer` (only `riu`; no weekend service), `none` (holidays and closures), and `reduced`/`holiday` variants where OCCT publishes them (for example no Inner Loop on holidays).
- Date ranges come from Binghamton's official academic calendar and OCCT's passenger notices: semester start/end, fall break, Thanksgiving break, winter break and interim weeks, spring break, finals and move-out, summer sessions. **Source every date with a URL in the file.** If you can't verify a date, leave it out, list it in `CALENDAR_TODO.md`, and **do not guess**. Ask me at the end for the dates you couldn't verify.
- Seasonal lines (`riu` = Summer Only, `ics` = Interim Weeks Only; see `meta.excluded_seasonal`) must be parsed and kept, with the calendar deciding when they run. They should not be dropped.
- Dataset versioning: each schedule set has `effective_from`/`effective_to`. The API picks the set in force on the query's service day, so Spring 2027 can be promoted ahead of time and switches over automatically. Outside any known range, return results with a prominent `stale_data` warning rather than confidently wrong times.
- One-off overrides (`data/overrides.json`): detours, closed stops, cancelled trips, and special-event service, each with a date range, reason, and source. They are applied after the calendar.

## 4. Routing engine

- Replace the per-route scan with **RAPTOR or Connection Scan** over the normalized dataset (pure Python, no new heavy dependencies, precomputed at import so Vercel cold starts stay fast; measure it).
- Query modes: **leave now**, **depart at** (date+time), **arrive by**. Search across the service-day boundary (an 11:30 PM query must find 12:45 AM Late Nite runs, and a 1:15 AM query on Saturday must find Friday-night service).
- Walking: use haversine × 1.3 detour factor at 80 m/min. Cap access/egress walking (default 800 m, configurable per request up to 2 km), apply a transfer walking cap, and use a minimum transfer buffer of 2 min. Add a code comment that this is a shortcut and real walking paths would be the upgrade.
- Offer a walk-only option when walking beats every bus, or when no bus runs (for example the destination is 600 m away).
- Return a Pareto set (arrival time × transfers), 3–5 journeys, each with legs: walk / ride (line, direction headsign, board stop, alight stop, times, scheduled|estimated, intermediate stops) / transfer.
- Clear empty states: "No service today (Thanksgiving break)", "Last bus has left; next service Mon 7:15 AM", "Late Nite runs Fri & Sat nights only".

## 5. Geocoding and input

- Keep stop-name snapping first. Add a **campus place alias table** (Bartle Library, Hinman, Mountainview, CIW, Dickinson, Newing, Events Center, ITC, UClub, Lecture Hall, East/West Gym, Wegmans Vestal, Oakdale Mall, downtown State St…) with coordinates sourced from OSM, so students don't need street addresses.
- Bound geocoding to the Binghamton/Vestal/Johnson City area and reject results outside a bounding box. Respect the Nominatim policy (≤1 req/s, identifying User-Agent, cache results). `lru_cache` is per serverless instance; that's acceptable, and a comment should say so.
- Validate input at the boundary (length limits, empty strings). Add basic rate limiting or at least a per-request geocode cap so the endpoint can't be used as a free geocoding proxy. Never log or expose the Google key.

## 6. Keeping schedules current (update workflow)

- Generalize the pipeline away from a hard-coded `SEASON = "fall2026"` (use a CLI arg).
- `scripts/check_for_updates.py`: fetch the index and each route page, hash the normalized schedule table content (not the whole page, which has volatile markup), and compare against the committed snapshot. Exit non-zero with a human-readable diff of added, removed, or renamed lines and changed times. Scrape politely: sequential, with a delay. Also watch OCCT's Passenger Notices for service alerts.
- `.github/workflows/schedule-watch.yml`: a weekly cron (daily in the two weeks before each semester) that runs the check, and on change runs scrape → `build_dataset.py --strict`, then **opens a PR** with the candidate plus a diff summary. It never auto-promotes to live data.
- `scripts/promote.py`: validate the candidate (strict build passes, every trip's times are monotonic with at most one midnight wrap, every stop has coordinates or an explicit TODO, the calendar covers the effective range), then swap it in atomically.
- Add an `/api/meta` endpoint (dataset effective range, fetched_at, active service profile today, active alerts). The UI shows "Schedule: Fall 2026 · updated Aug 24" and an alert banner.

## 7. Frontend

- Add a time mode selector (Leave now / Depart at / Arrive by) with date+time, an itinerary view showing legs, a transfer indicator, a "~" for estimated times, a "Late Nite" badge, a service alert banner, and a stale-data warning.
- Optional (only if everything else is done): a Leaflet map showing stops and the walking/ride legs (pin the library version, CDN only). It should degrade gracefully without the map.
- Make it accessible: labelled inputs, keyboard-operable, and announce results with `aria-live`. Make it mobile-first, since most use is on phones at a bus stop. Keep the existing theme toggle and vanilla-JS approach (no framework).
- Encode queries in the URL so routes can be shared and bookmarked. Don't put any personal data in the URL beyond what the user typed.

## 8. Out of scope unless it turns out to be cheap

- Real-time bus positions: check whether OCCT publishes a public live-tracking feed. If a documented public one exists, write a short integration plan in `REALTIME.md` and don't build it. Don't scrape private endpoints.
- Broome County Transit transfers: out of scope, but leave the stop model able to hold another agency's stops.
- GTFS export: if your internal model already follows GTFS, a `scripts/export_gtfs.py` that writes a valid static feed is a nice bonus (it lets Google Maps and OpenTripPlanner consume it later).

## 9. Tests (required; use pytest and add it to `requirements-dev.txt`)

Freeze "now" in every time-dependent test. At minimum:

- A weekday 8 AM campus → downtown query returns a direct trip with correct times.
- Friday 11:40 PM and Saturday 12:30 AM queries both find the 12:45 AM Late Nite run. A Sunday 12:30 AM query does too (Sat night service). A Tuesday 12:30 AM query does not.
- Friday is a holiday (`none`) → Saturday's 12:45 AM run is also gone.
- A Thanksgiving-break date returns "no service" with the reason. An interim-week date returns only ITC–Campus Shuttle results.
- A loop line where origin is the terminus works, and a stop visited twice uses the correct visit.
- A trip marked "Skips Acad A" is never offered for boarding at Hinman/Academic A.
- A one-transfer journey is found when no direct route exists, and the transfer buffer is respected.
- Arrive-by returns the latest departure that still makes it.
- DST: a query on 2026-11-01 between 1–2 AM and one on 2027-03-14 behave sensibly.
- Outside every dataset's effective range, the `stale_data` warning is set.
- Parser golden tests against the committed `data/raw/fall2026/*.html` snapshots, and `build_dataset.py --strict` passes.
- API contract tests for `/api/route`, `/api/meta`, and `/api/stops`, plus bad-input 400s.

## 10. Ground rules

- **Never fabricate schedule times, dates, or coordinates.** Anything unverifiable goes into a TODO file with what's needed to resolve it.
- Small, reviewable commits (one concern each). Don't commit `.DS_Store` or `__pycache__` (add them to `.gitignore` and remove them from the index). Don't push or deploy. I'll review first.
- Keep runtime dependencies minimal (FastAPI, requests, standard library `zoneinfo`; add `tzdata` only if Vercel's image lacks zone data, and verify that). No database: JSON files loaded at import are fine at this scale.
- Keep the API backward compatible for one release (the old response shape stays available or the frontend updates in the same commit).
- Run `vercel dev` or `uvicorn` locally and click through the UI in a browser before you call it done.

## 11. Done means

All tests pass. `build_dataset.py --strict` passes. The API serves the normalized dataset with calendar-aware, timezone-correct, transfer-capable routing. The update workflow opens PRs instead of silently changing live data. The UI shows legs, estimated vs. scheduled times, alerts, and data freshness. Finish with a summary covering what changed, what you verified and how, every TODO (calendar dates, coordinates, aliases you judged), and the questions you need me to answer.
