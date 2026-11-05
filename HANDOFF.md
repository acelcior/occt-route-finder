# Maintainer handoff

Read this first if you inherit the planner. Everything routine is a JSON edit plus
`make` commands; Python only changes when OCCT changes how its website is built.

## 1. What runs where

| Piece | Where | Who must have access |
|---|---|---|
| Code + data | GitHub `acelcior/occt-route-finder`, branch `main` | repo admin (to transfer) |
| Hosting | Vercel project `occt-route-finder` (team "acelerating-gmailcom's projects"), auto-deploys `main` | Vercel project owner |
| Optional geocoding | `GOOGLE_API_KEY` env var on Vercel (falls back to OpenStreetMap/Nominatim if unset) | whoever owns the key |
| Live bus data | none — links to ETA Transit; see `REALTIME.md` | — |

Deploy = merge to `main`. There is no build step; Vercel installs `requirements.txt`
and serves `public/` + `src/api/index.py`.

## 2. The semester cycle (when to act)

| When | What to do |
|---|---|
| ~2 weeks before a semester (early Aug / early Jan) | OCCT posts a Semester Bulletin on https://occtransport.org/news.html with the first day of regular service → **§3 new season** |
| Weekly during the semester | the `schedule-watch` Action opens a PR if any timetable changed → review, merge, `make promote`, merge |
| When OCCT posts a holiday notice (Labor Day, Thanksgiving ~Nov 20, winter ~Dec 5, spring break ~Mar 1, finals) | **§4 calendar**: flip the matching `provisional` period to `confirmed`, fix dates/profile |
| A one-off cancellation, detour, closed stop | **§5 overrides** |
| The footer shows "service calendar ends …" or "timetable is over N months old" | the data is about to go stale → §3 / §4 |

## 3. New season (e.g. Spring 2027)

```bash
make setup                                   # once per machine
# 1. register the season (effective_from = first day of REGULAR service from the bulletin)
#    data/build_config.json -> "seasons": add {"spring2027": {"label": "Spring 2027",
#    "effective_from": "2027-01-19", "effective_to": null, "source": "<bulletin url + quote>"}}
make snapshot SEASON=spring2027              # fetch occtransport.org into data/raw/spring2027/
make build SEASON=spring2027                 # strict parse -> data/occt_dataset.spring2027.candidate.json
# fix every reported error (see §6), re-run until clean
make promote SEASON=spring2027               # validates + smoke-tests, writes data/occt_dataset.spring2027.json
make test
git add -A && git commit -m "data: Spring 2027 schedule" && git push
```

The API picks the dataset whose `effective_from` is the latest one on or before the
query date, so promoting Spring early does not affect Fall queries. Leave the old
season's files in place for history; delete them only if the repo gets heavy.

Then extend `data/service_calendar.json` (§4) through the end of the new semester.

## 4. Service calendar (`data/service_calendar.json`)

One entry per date range; shorter ranges override longer ones. Profiles:
`regular`, `alternate` (regular + warning), `interim` (ICS only), `summer` (RIU only), `none`.

- `status: "confirmed"` = OCCT announced it (put the notice URL in `source`).
- `status: "provisional"` = taken from the BU academic calendar + what OCCT did last
  year; the site shows a warning on those days. `CALENDAR_TODO.md` lists every open one.
- Dates with no entry show the regular timetable with an "unknown calendar" warning.

The academic calendar is at https://www.binghamton.edu/academics/academic-calendar.html
(it already lists the next two years). Add next semester's breaks as `provisional`
as soon as you add the season.

## 5. Overrides (`data/overrides.json`)

Short-lived changes that are not a new timetable: `alert` (message only),
`cancel_line` (e.g. Downtown Express cancelled this Saturday), `close_stop`
(stop under construction). Each needs `from`/`to` dates, `message`, `source`.
Commit, push; it is live in ~1 minute. Remove or let expire afterwards.

## 6. When OCCT changes stops or routes

`make build` fails loudly rather than guessing. What each error means:

| Error | Fix |
|---|---|
| `unresolved timepoint 'X'` | a timetable column header does not match a stop on that line → add `"x": "Canonical Stop Name"` to `timepoint_aliases` in `data/build_config.json` |
| `ambiguous timepoint` | the header matches several stops → same fix, naming the right one |
| `unknown day flag 'x'` | a new row tag like "No Thu" → add it to `DAY_FLAGS` in `scripts/build_dataset.py` (this one is code) |
| `index lists route page 'xy' that PAGES does not configure` | OCCT added a route → add it to `pages` (shape `scroll` if the page's stop list is in running order, otherwise `timepoints`) |
| `no stop-scroll found` / `row has N cells` / `frequency hours … not found` | OCCT changed the page markup → `scripts/build_dataset.py` needs a developer |
| `STOPS WITHOUT COORDINATES` (not an error) | new stop → add it to `data/places.json` with an OpenStreetMap source (`kind: "stop"`); never guess coordinates |

A renamed stop usually shows up as a *new* stop with no coordinates plus the old one
disappearing from the lines. Add the new spelling to `stop_aliases` so it keeps the
same id (transfers and coordinates depend on it). The opposite case — one name used for
two different curbs on two lines (DCL's and WS's "Murray Street") — goes in
`page_stop_renames`, keyed by the route page it appears on.

Placing a new stop: find the OSM node where the stop's street meets the road the line
runs on (OCCT's route page says which road) — `scripts/` has no tool for this yet, the
Overpass query used in Nov 2026 is recorded in `CALENDAR_TODO.md` — and add it to
`data/places.json` with the node URL as `source`. Never type coordinates from memory.

`make check` (or the weekly Action) tells you *what* changed on the live site before
you rebuild. The committed snapshot in `data/raw/<season>/` is the source of truth;
the parser never runs against the live site directly.

## 7. Automation

- `.github/workflows/ci.yml`: tests on every push/PR, and checks that each live
  dataset equals a strict rebuild of its snapshot (catches hand edits).
- `.github/workflows/schedule-watch.yml`: weekly (daily in Jan/Aug) diff against
  occtransport.org; on change it refreshes the snapshot, rebuilds the candidate and
  opens a PR. It never promotes. Requires the repo setting *Settings → Actions →
  General → "Allow GitHub Actions to create and approve pull requests"*. Set the
  repo variable `OCCT_SEASON` when the season changes (defaults to `fall2026`).

## 8. Shipping it to occtransport.org

Pick by how much OCCT wants to own:

1. **Link** — add "Trip planner" in their nav pointing at the Vercel URL. Zero work.
2. **Embed** — on any occtransport.org page:
   ```html
   <iframe src="https://occt-route-finder.vercel.app/" title="OCCT trip planner"
           style="width:100%;min-height:900px;border:0"></iframe>
   ```
3. **Host the page on their site, keep the API here** — copy `public/` into their
   site and put this before `app.js`:
   ```html
   <script>window.OCCT_API_BASE = "https://occt-route-finder.vercel.app";</script>
   ```
   The API already allows `https://occtransport.org` and `https://www.occtransport.org`
   (env `ALLOWED_ORIGINS` on Vercel to change). The page already uses their fonts,
   colours and nav pattern, so it drops into their layout.
4. **Move everything to OCCT** — transfer the GitHub repo and the Vercel project
   (Vercel: *Project Settings → General → Transfer*), or deploy the FastAPI app
   anywhere that runs Python 3.12 (`uvicorn api.index:app --app-dir src`).
5. **Long term** — the dataset is one small step from GTFS (`stops`, `routes`,
   `trips`, `stop_times`, `calendar_dates`). If OCCT ever publishes GTFS (its ETA
   Transit vendor can), replace `scripts/build_dataset.py` with a GTFS loader and the
   scraping disappears; Google/Apple Maps and Transit app then pick OCCT up too.

## 9. Handing the project to someone else

1. Transfer the GitHub repo (Settings → Danger zone → Transfer) and the Vercel project.
2. Rotate / re-issue `GOOGLE_API_KEY` if one is set.
3. Change the contact e-mail in `USER_AGENT` in `scripts/scrape_schedules.py` and
   `NOMINATIM_UA` in `src/api/index.py` (OpenStreetMap's policy requires a real contact).
4. Run `make setup && make test` on the new machine — 34 tests must pass.
5. Read `CALENDAR_TODO.md` for what is still unconfirmed.

## 10. If something looks wrong on the live site

| Symptom | Cause / fix |
|---|---|
| "Cannot read properties of undefined" | an old tab from before a deploy; reload. Assets are versioned (`?v=N` in `public/index.html`) — bump N when you change `app.js`/`style.css` |
| Times are off by hours | the server lost `tzdata`; it is in `requirements.txt`, check the Vercel build log |
| "No OCCT service on …" on a normal day | a wrong `none` period in `service_calendar.json` |
| A stop can't be found by name | it has no coordinates (`stops_missing_coords` in the dataset) or needs an alias in `build_config.json` |
| Preview deployment asks for a Vercel login | expected: Vercel Authentication is on for non-production URLs |
