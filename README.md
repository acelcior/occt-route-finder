# OCCT Route Finder

Trip planner for Binghamton University's OCCT buses: campus ⇄ downtown ⇄ Johnson City /
Vestal, with transfers, Late Nite service, the academic-year service calendar and
"depart at" / "arrive by" queries. Runs as a FastAPI function on Vercel with a static
vanilla-JS frontend.

**Maintaining it:** read [HANDOFF.md](HANDOFF.md) — the semester cycle, adding a season,
what to edit when OCCT changes a stop, and how to put it on occtransport.org.
`make help` lists the commands.

## Layout

| Path | What |
|---|---|
| `src/planner.py` | Routing engine: RAPTOR over the normalized dataset, service calendar, walking, journeys |
| `src/api/index.py` | HTTP API (`/api/route`, `/api/meta`, `/api/stops`, `/api/health`), geocoding |
| `src/stop_names.py` | Stop-name normalization |
| `public/` | Frontend (`index.html`, `app.js`, `style.css`) |
| `data/occt_dataset.<season>.json` | **Live** normalized schedule (stops, lines, directions, trips, untimed loops) |
| `data/occt_dataset.<season>.candidate.json` | Freshly built, not yet promoted |
| `data/service_calendar.json` | Which service profile applies on each date (sourced; `confirmed`/`provisional`) |
| `data/overrides.json` | One-off alerts, cancelled lines, closed stops |
| `data/places.json` | OSM-sourced coordinates for campus places and stops the cache lacked |
| `data/stop_cache.json` | Older stop coordinate cache (still used where `places.json` has nothing) |
| `data/raw/<season>/` | Committed snapshot of occtransport.org route pages |
| `scripts/scrape_schedules.py` | Snapshot the live site |
| `scripts/check_for_updates.py` | Diff live schedule content vs snapshot (used by the GitHub Action) |
| `scripts/build_dataset.py` | Parse + validate snapshot → candidate dataset (`--strict`) |
| `scripts/promote.py` | Validate candidate, smoke-test the planner, swap it in |
| `.github/workflows/schedule-watch.yml` | Weekly check; opens a PR when OCCT changes a schedule |
| `tests/` | pytest suite (frozen times) |

## Time model (read this before touching trips)

Trips carry **service days** and minutes after the service day's midnight that may exceed
1440. A Late Nite run at 12:45 AM Saturday is `days=["Fri"], min=1485`. If Friday is a
no-service day, that run disappears too. All times are America/New_York.

## Commands

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
.venv/bin/uvicorn api.index:app --app-dir src --reload   # then open public/ via vercel dev, or see below
```

Local full stack: `vercel dev` (serves `public/` and the function), or run uvicorn and
serve `public/` with any static server pointing `/api` at it.

Schedule update cycle:

```bash
.venv/bin/python scripts/check_for_updates.py --season fall2026 --write   # exit 1 = changed
.venv/bin/python scripts/build_dataset.py --season fall2026 --strict
# review data/occt_dataset.fall2026.candidate.json (git diff is readable)
.venv/bin/python scripts/promote.py --season fall2026
```

New semester: add the season to `SEASONS` in `scripts/build_dataset.py` with the
`effective_from` date from OCCT's semester bulletin, snapshot into `data/raw/<season>/`,
build, promote, and extend `data/service_calendar.json`. The API picks the dataset whose
effective range covers the query date, so the next semester can be promoted early.

## Known limits

- Intermediate stop times are interpolated between OCCT's published timepoints and shown
  with "~". Campus Shuttle daytime loops have no timetable and are shown untimed.
- Walking is straight-line × 1.3 at 80 m/min, capped at 2 km to a stop and 400 m for transfers.
- Provisional calendar entries (see `CALENDAR_TODO.md`) show a warning until OCCT confirms.
- No real-time data (see `REALTIME.md`).
