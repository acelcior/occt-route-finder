# Service calendar: what still needs confirming

`data/service_calendar.json` marks every period `confirmed` (OCCT announced it) or
`provisional` (Binghamton University academic calendar + the pattern OCCT followed in
2024–2026; the OCCT notice is not posted yet). The API shows a warning on provisional
days. Confirm each item below against https://occtransport.org/news.html when the
notice appears, then flip `status` to `confirmed` (or correct the dates/profile).

## Provisional periods (Fall 2026 → Fall 2027)

| Dates | Assumed service | Basis |
|---|---|---|
| Tue 2026-11-24 | regular, early end (~10:45 PM in 2025) | BU calendar; 2025 Thanksgiving notice |
| Wed 2026-11-25 | ICS only, morning (8 AM–12 PM in 2025) | same |
| Thu 2026-11-26 – Sun 11-29 | no service | same (2024 + 2025 pattern) |
| Thu 2026-12-17 – Fri 12-18 | ICS only | finals end Wed 12-16; 2025 pattern |
| Sat 12-19 – Sun 12-20 | no service | 2025 pattern |
| Mon 12-21 – Wed 12-23 | ICS only (weekdays) | 2025: ICS Dec 15–23 |
| Thu 12-24 – Sun 2027-01-03 | no service | BU winter session break |
| Mon 01-04 – Fri 01-15 | ICS only (weekdays) | BU winter session; 2026: ICS Jan 5–16 |
| Sat 01-16 – Mon 01-18 | alternate (Welcome Back) | move-in weekend |
| Tue 2027-01-19 – Fri 05-14 | regular | classes begin Jan 19 |
| Fri 03-05 | regular, early end | Spring Break eve pattern |
| Sat 03-06 – Sun 03-07, Sat 03-13 – Sun 03-14 | no service | 2026 Spring Break notice pattern |
| Mon 03-08 – Fri 03-12 | ICS only | same |
| Thu 04-22 – Fri 04-23 (Passover) | regular, maybe reduced / no Late Nite | 2025 Easter pattern |
| Fri 05-14 | regular, ends midday | 2025: "regular service ends midday Friday" |
| Sat 05-15 – Sun 05-16 | no service | commencement weekend |
| Mon 05-17 – Fri 05-21 | ICS only | 2025 interim pattern |
| Mon 05-24 – Fri 08-06 | summer (RIU only, weekdays) | BU summer sessions; 2025: summer began the Tue after interim |
| 05-31, 06-18, 07-05 | no service | Memorial Day, Juneteenth (observed), Independence Day (observed) |
| Mon 08-09 – Thu 08-12 | ICS only | 2026 pattern |
| Fri 08-13 – Mon 08-23 | alternate (Welcome Back) | 2026 pattern |
| Tue 08-24 – Wed 12-15 | regular | Fall 2027 classes Aug 24 |

Not entered at all (no data): Fall 2027 holidays (Labor Day 09-06, Rejuvenation Day /
Rosh Hashanah 10-01/02, Yom Kippur 10-11, Thanksgiving 11-24..28), Spring 2028.

## Questions for OCCT / the maintainer

1. **Late Nite "in effect" dates** — route pages say Late Nite runs "Fri & Sat nights only
   when Late Nite service is in effect". The calendar assumes it runs every regular-service
   weekend. In 2025 it was cancelled on Rejuvenation Day and Labor Day weekends; no such
   notice exists for fall 2026 yet. Add an `overrides.json` entry (`cancel_line` is per line;
   Late Nite is a tier — add a `cancel_tier` kind if needed) when OCCT announces one.
2. **Alternate Saturday master schedules** (OCCT ran them on several 2025/2026 Saturdays).
   They are not modelled; on such a date set an `alert` override so riders are warned.
3. **Reduced-service days** (Labor Day weekend, religious holidays): OCCT publishes a
   reduced timetable we do not have. Modelled as regular + warning only.
4. **Early-end days**: the planner cannot cut a day short without the "final runs" list.
   Add `cancel_trip`-style overrides when OCCT posts them (not implemented yet).

## Stops without coordinates (excluded from map snapping, still searchable by name)

- `admissions` — Admissions Center (Inner Loop). No OSM feature found.
- `decker_health_services` — Decker Student Health Services (Outer Loop, by request).
- `lot_b_old_dickinson` — Lot B (Inner Loop). No OSM feature found.
- `hayes` — UClub/IU/RIU stop "Hayes" near Meadows / University Plaza. The old cache
  pointed at Hayes St in Binghamton's south side (wrong); no OSM match near Vestal.

## Judgment calls baked into `scripts/build_dataset.py` (confirm with OCCT)

- Downtown Express "Returns to Campus" column = Hinman / Academic A (page lists it as
  the stop before returning to the Union).
- Campus Shuttle Blue Bus "Returns to Lower Campus" column = Hinman / Academic A.
- Campus Shuttle fixed schedules (evening, weekend, Late Nite) only include the five
  published timepoints; OCCT does not publish the order/times of the other stops.
- "Meadows & Hayes" timepoint on the ITC–UClub Shuttle resolves to Meadows.
- Lot D / Lot K / Lot C / Lot U / Rafuse coordinates are OSM parking-lot / building
  centroids, not the curb.
