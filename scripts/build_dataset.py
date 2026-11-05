"""Build the normalized OCCT dataset from one season's raw HTML snapshots.

Runs OFFLINE against ``data/raw/<season>/`` (written by ``scrape_schedules.py``)
and writes ``data/occt_dataset.<season>.candidate.json``. Review the candidate,
then ``scripts/promote.py`` validates it and copies it to the live name
``data/occt_dataset.<season>.json`` that the API serves.

Output schema
-------------
::

    {"meta":  {"season","label","effective_from","effective_to","fetched_at",
               "built_at","seasonal_lines","stops_missing_coords"},
     "stops": {stop_id: {"name", "lat", "lon", "aliases": [raw labels seen]}},
     "lines": [{"id","name","url","seasonal"?,
                "directions": {dir_key: {"label","headsign","stops":[stop_id,...]}},
                "trips": [{"direction","tier","days":[service-day codes],
                           "skip_stops"?:[stop_id], "note"?,
                           "times":[{"seq","stop","time","min"}]}],
                "frequency": [{"key","name","days","start_min","end_min",
                               "stops":[stop_id], "note", "no_holidays"?}]}]}

Modelling decisions
-------------------
* **Service day, not calendar day.** ``days`` are the days the trip's *service*
  belongs to and ``min`` is minutes after that service day's midnight, so a
  Late Nite run at 12:45 AM on a Saturday night is ``days=["Sat"], min=1485``.
  Any clock time before ``NIGHT_CUTOFF_MIN`` (4 AM) is late service of the
  previous day; OCCT's earliest morning run is 7:00 AM so this is unambiguous.
  "Fri & Sat nights" Late Nite tables therefore get ``days=["Fri","Sat"]``.
  Row tags ("Sat only", "No Fri") name the service day.
* **Canonical stops.** OCCT spells the same curb several ways across pages
  ("Univ. Union", "University Union", "Court & Hawley" / "Hawley & Court").
  ``STOP_ALIASES`` folds them to one id so transfers and coordinates line up.
* **Timepoints only where OCCT gives nothing better.** For the Campus Shuttle
  and Downtown Express the page's stop list is not in running order (or is
  absent), so a trip's stops are just its timepoint columns. The daytime Campus
  Shuttle loops have no timetable at all and are stored as ``frequency``
  services (hours parsed from the page) that the planner shows untimed.
* **"Skips Acad A" means the bus does not stop there**: recorded as
  ``skip_stops`` so the planner never boards/alights a trip at a skipped stop.
* Every unresolved header / unknown tag / non-monotonic trip is an error.
  ``--strict`` refuses to write while any remain.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from stop_names import normalize_stop_name  # noqa: E402
from scrape_schedules import parse_index  # noqa: E402

MON_FRI = ["Mon", "Tue", "Wed", "Thu", "Fri"]
SAT_SUN = ["Sat", "Sun"]
FRI_SAT = ["Fri", "Sat"]
NIGHT_CUTOFF_MIN = 4 * 60

# Routine-update configuration lives in data/build_config.json (seasons, pages,
# stop and timepoint aliases, seasonal lines) so maintainers edit data, not code.
CONFIG = json.loads((ROOT / "data" / "build_config.json").read_text(encoding="utf-8"))
SEASONS: dict[str, dict[str, Any]] = CONFIG["seasons"]
SEASONAL_LINES: dict[str, str] = CONFIG["seasonal_lines"]
PAGES: dict[str, dict[str, Any]] = CONFIG["pages"]
STOP_ALIASES: dict[str, str] = CONFIG["stop_aliases"]
TIMEPOINT_ALIASES: dict[str, str] = CONFIG["timepoint_aliases"]
# page slug -> {name on that page: distinct canonical name}, for stops that share a
# name with a different physical stop on another line (e.g. two "Murray Street"s).
PAGE_STOP_RENAMES: dict[str, dict[str, str]] = CONFIG.get("page_stop_renames", {})

# Untimed continuous loops. Hours are parsed from the page text with these
# patterns so a site change is caught; stop lists come from the page's
# stop-scroll blocks (index into the page's .stop-scroll elements).
FREQUENCY_SERVICES: dict[str, list[dict[str, Any]]] = {
    "cs": [
        {"key": "outer-loop", "name": "Outer Loop (daytime green shuttle)",
         "scroll": 0, "expect_stops": 16, "days": MON_FRI,
         "hours_re": r"Mon–Fri\s+(\d{1,2}:\d{2}\s*[AP]M)\s+to\s+(\d{1,2}:\d{2}\s*[AP]M)",
         "note": "Continuous loop with no fixed timetable; check ETA Transit for live "
                 "arrivals. Buses from the Engineering Building do not serve Mohawk "
                 "and vice versa."},
        {"key": "inner-loop", "name": "Inner Loop (around the Brain)",
         "scroll": 1, "expect_stops": 7, "days": MON_FRI, "no_holidays": True,
         "hours_re": r"Monday–Friday,\s+(\d{1,2}:\d{2}\s*[AP]M)\s+to\s+(\d{1,2}:\d{2}\s*[AP]M)",
         "note": "Continuous loop with no fixed timetable; check ETA Transit. "
                 "No service evenings, weekends or holidays."},
    ],
}

# Row day-qualifier tag -> service-day override and/or stops skipped.
DAY_FLAGS: dict[str, dict[str, Any]] = {
    "no fri": {"days": ["Mon", "Tue", "Wed", "Thu"], "note": "No Friday service"},
    "sat only": {"days": ["Sat"], "note": "Saturday only"},
    "sun only": {"days": ["Sun"], "note": "Sunday only"},
    "fri only": {"days": ["Fri"], "note": "Friday only"},
    "skips acad a": {"skip": "Hinman / Academic A", "note": "Does not stop at Hinman / Academic A"},
    "no acad a": {"skip": "Hinman / Academic A", "note": "Does not stop at Hinman / Academic A"},
}


def canon_norm(label: str) -> str:
    """Normalized form of a label after alias folding."""
    n = normalize_stop_name(label.rstrip(" *").strip())
    if n in STOP_ALIASES:
        return normalize_stop_name(STOP_ALIASES[n])
    return n


def to_min(s: str) -> int | None:
    try:
        dt = datetime.strptime(s.strip(), "%I:%M %p")
    except ValueError:
        return None
    return dt.hour * 60 + dt.minute


def service_minutes(time_strs: list[str]) -> list[int] | None:
    """Clock times -> minutes after the service day's midnight (may exceed 1440).

    Allows one midnight wrap inside a trip; a trip starting before the night
    cutoff is entirely late service of the previous day.
    """
    mins = [to_min(t) for t in time_strs]
    if any(m is None for m in mins):
        return None
    carry = 1440 if mins[0] < NIGHT_CUTOFF_MIN else 0
    out: list[int] = []
    for m in mins:
        v = m + carry
        if out and v < out[-1]:
            carry += 1440
            v = m + carry
        out.append(v)
    return out


class Builder:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.stops: dict[str, dict[str, Any]] = {}
        self.norm_to_id: dict[str, str] = {}
        self._load_coords()

    def _load_coords(self) -> None:
        self.coord_by_norm: dict[str, dict[str, float]] = {}
        # places.json first: every entry there is OSM-sourced and overrides the older cache.
        sources = [ROOT / "data" / "places.json", ROOT / "data" / "stop_cache.json"]
        for p in sources:
            if not p.exists():
                continue
            for k, v in json.loads(p.read_text()).items():
                if k.startswith("_") or not isinstance(v, dict):
                    continue
                if v.get("lat") is None:
                    if p.name == "places.json" and "lat" in v:
                        # explicit "location unknown": blocks a wrong guess in an older source
                        self.coord_by_norm.setdefault(canon_norm(k), None)
                    continue
                self.coord_by_norm.setdefault(canon_norm(k), {"lat": v["lat"], "lon": v["lon"]})
        legacy = ROOT / "data" / "occt_routes_geo.json"
        if legacy.exists():
            for r in json.loads(legacy.read_text()):
                for nm, loc in (r.get("stop_coords") or {}).items():
                    if loc:
                        self.coord_by_norm.setdefault(canon_norm(nm), loc)

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    # -- stop registry --------------------------------------------------------
    def stop_id(self, raw_name: str) -> str:
        raw = raw_name.rstrip(" *").strip()
        norm = canon_norm(raw)
        if norm in self.norm_to_id:
            sid = self.norm_to_id[norm]
        else:
            sid = re.sub(r"[^a-z0-9]+", "_", norm).strip("_")
            canonical = STOP_ALIASES.get(normalize_stop_name(raw), raw)
            loc = self.coord_by_norm.get(norm)
            self.stops[sid] = {
                "name": canonical,
                "lat": float(loc["lat"]) if loc else None,
                "lon": float(loc["lon"]) if loc else None,
                "aliases": [],
            }
            self.norm_to_id[norm] = sid
        entry = self.stops[sid]
        if raw != entry["name"] and raw not in entry["aliases"]:
            entry["aliases"].append(raw)
        return sid

    def stop_norm(self, sid: str) -> str:
        return normalize_stop_name(self.stops[sid]["name"])

    # -- timepoint header resolution -----------------------------------------
    @staticmethod
    def header_core(header: str) -> str:
        label = re.sub(r"\s+", " ", header).strip()
        core = re.sub(r"^(depart|leaves)\s+", "", label, flags=re.I)
        # "BU Arrive UDC" -> "BU"; a header that *starts* with Arrive/Returns keeps its stop.
        core = re.sub(r"(?<=\S)\s+(arrive|returns to|return to)\s.*$", "", core, flags=re.I)
        core = re.sub(r"^(arrive|returns to|return to)\s+", "", core, flags=re.I)
        return core

    def resolve_header_pos(self, header: str, col: int, ncols: int,
                           dir_stop_ids: list[str], prev_pos: int, where: str) -> int | None:
        """Header cell -> POSITION in the direction's stop sequence (loops may
        revisit a stop, so positions rather than ids)."""
        label = re.sub(r"\s+", " ", header).strip()
        low = label.lower()
        core = self.header_core(label)
        target = canon_norm(TIMEPOINT_ALIASES[low]) if low in TIMEPOINT_ALIASES else canon_norm(core)
        n = len(dir_stop_ids)
        exact = [i for i, s in enumerate(dir_stop_ids) if self.stop_norm(s) == target and i > prev_pos]
        if exact:
            return exact[0]
        htok = set(target.split())
        subset = [i for i, s in enumerate(dir_stop_ids)
                  if htok and htok <= set(self.stop_norm(s).split()) and i > prev_pos]
        if len(subset) == 1:
            return subset[0]
        # Positional fallback for endpoint abbreviations ("UDC", "BU") that share
        # no tokens with the full stop name: first column is the origin, last the terminus.
        if col == 0 and prev_pos < 0:
            return 0
        if col == ncols - 1:
            return n - 1
        if len(subset) > 1:
            self.err(f"{where}: ambiguous timepoint {label!r} -> "
                     f"{[self.stops[dir_stop_ids[i]]['name'] for i in subset]}")
        else:
            self.err(f"{where}: unresolved timepoint {label!r}; add a TIMEPOINT_ALIASES entry")
        return None

    # -- HTML helpers ---------------------------------------------------------
    @staticmethod
    def wrapper_id(tbl) -> str:
        for a in tbl.parents:
            if a.has_attr("id"):
                return a["id"]
        return "??"

    @staticmethod
    def scroll_names(soup) -> list[list[str]]:
        return [[e.get_text(" ", strip=True) for e in blk.select(".stop-name")]
                for blk in soup.select(".stop-scroll")]

    @staticmethod
    def scroll_for_table(tbl) -> tuple[list[str] | None, str | None]:
        """The direction's stop list is the .stop-scroll in the table's closest
        container; that container's id is the direction key."""
        for anc in tbl.parents:
            sc = anc.select_one(".stop-scroll") if hasattr(anc, "select_one") else None
            if sc is not None:
                return [e.get_text(" ", strip=True) for e in sc.select(".stop-name")], (anc.get("id") or None)
        return None, None

    @staticmethod
    def decode_id(wid: str) -> tuple[str, list[str]]:
        """container id -> (tier, base service days)."""
        low = wid.lower()
        parts = low.split("-")
        if "ln" in parts:
            return "latenite", FRI_SAT          # "Fri & Sat nights"
        if low.endswith("wkd"):
            return "regular", MON_FRI
        if low.endswith("wkn"):
            return "regular", SAT_SUN
        if low.endswith("fri"):
            return "regular", ["Fri"]
        if low.endswith("sat"):
            return "regular", ["Sat"]
        return "regular", MON_FRI

    @staticmethod
    def direction_label(dir_key: str) -> str:
        parts = dir_key.lower().split("-")
        bits = []
        if "ln" in parts:
            bits.append("Late Nite")
        if "out" in parts or parts[0] == "ro":
            bits.append("Outbound")
        elif "in" in parts or parts[0] == "ri":
            bits.append("Inbound")
        return " ".join(bits)

    # -- frequency (untimed) services -----------------------------------------
    def frequency_services(self, slug: str, soup, where: str) -> list[dict[str, Any]]:
        text = re.sub(r"\s+", " ", soup.get_text(" ").replace("\xa0", " "))
        scrolls = self.scroll_names(soup)
        out = []
        for cfg in FREQUENCY_SERVICES.get(slug, []):
            m = re.search(cfg["hours_re"], text)
            if not m:
                self.err(f"{where}: frequency hours for {cfg['key']} not found on page")
                continue
            start, end = to_min(m.group(1)), to_min(m.group(2))
            if cfg["scroll"] >= len(scrolls) or len(scrolls[cfg["scroll"]]) != cfg["expect_stops"]:
                self.err(f"{where}: stop list for {cfg['key']} has unexpected shape")
                continue
            entry = {"key": cfg["key"], "name": cfg["name"], "days": cfg["days"],
                     "start_min": start, "end_min": end,
                     "stops": [self.stop_id(n) for n in scrolls[cfg["scroll"]]],
                     "note": cfg["note"]}
            if cfg.get("no_holidays"):
                entry["no_holidays"] = True
            out.append(entry)
        return out

    # -- one line ---------------------------------------------------------------
    def build_line(self, slug: str, cfg: dict[str, Any], html: str, url: str | None) -> dict[str, Any]:
        soup = BeautifulSoup(html, "html.parser")
        renames = PAGE_STOP_RENAMES.get(slug, {})
        register = self.stop_id
        self.stop_id = lambda n: register(renames.get(n.rstrip(" *").strip(), n))  # page-scoped names
        for names in self.scroll_names(soup):
            for n in names:
                self.stop_id(n)

        line: dict[str, Any] = {"id": slug, "name": cfg["name"], "url": url,
                                "directions": {}, "trips": []}
        if slug in SEASONAL_LINES:
            line["seasonal"] = SEASONAL_LINES[slug]
        sig_to_key: dict[tuple[str, ...], str] = {}

        for tbl in soup.select("table.sched-table"):
            wid = self.wrapper_id(tbl)
            headers = [th.get_text(" ", strip=True) for th in tbl.select("thead th")]
            ncols = len(headers)
            tier, base_days = self.decode_id(wid)
            where = f"{slug}:{wid}"

            if cfg["shape"] == "timepoints":
                dir_stop_ids = [self.stop_id(self.header_core(h)) for h in headers]
                raw_key = wid
            else:
                names, container = self.scroll_for_table(tbl)
                if names is None:
                    self.err(f"{where}: no stop-scroll found in any ancestor")
                    continue
                dir_stop_ids = [self.stop_id(n) for n in names]
                raw_key = container or wid

            # One direction per distinct stop sequence: weekday/weekend/late-nite
            # tables of the same loop share it, Downtown Express variants do not.
            sig = tuple(dir_stop_ids)
            if sig not in sig_to_key:
                base = re.sub(r"-(wkd|wkn|ln|fri|sat)$", "", raw_key)
                key, n = base, 1
                while key in sig_to_key.values():
                    key = f"{base}-{'abcdefgh'[n]}"
                    n += 1
                sig_to_key[sig] = key
            dir_key = sig_to_key[sig]

            names_seq = [self.stops[s]["name"] for s in dir_stop_ids]
            if cfg["shape"] == "timepoints":
                headsign = " → ".join(names_seq)
            elif names_seq[0] == names_seq[-1]:
                headsign = f"Loop from {names_seq[0]}"
            else:
                headsign = f"{names_seq[0]} → {names_seq[-1]}"
            line["directions"].setdefault(dir_key, {
                "label": self.direction_label(dir_key),
                "headsign": headsign,
                "stops": dir_stop_ids,
            })

            positions: list[int] = []
            prev = -1
            for i, h in enumerate(headers):
                p = self.resolve_header_pos(h, i, ncols, dir_stop_ids, prev, where)
                if p is None:
                    positions = []
                    break
                positions.append(p)
                prev = p
            if not positions:
                continue

            for tr in tbl.select("tbody tr"):
                tag = tr.select_one(".sched-day-tag")
                tag_text = tag.get_text(strip=True) if tag else ""
                flag = re.sub(r"\s+", " ", tag_text.replace("\xa0", " ")).strip().lower() or None
                cells = [td.get_text(" ", strip=True) for td in tr.select("td")]
                if tag:
                    cells = [c.replace(tag_text, "").strip() for c in cells]
                if len(cells) != ncols:
                    self.err(f"{where}: row has {len(cells)} cells, expected {ncols}")
                    continue
                kept = [(positions[i], cells[i]) for i in range(ncols) if to_min(cells[i]) is not None]
                skipped_cols = [i for i in range(ncols) if to_min(cells[i]) is None]
                if len(kept) < 2:
                    self.err(f"{where}: trip has <2 usable timepoints: {cells}")
                    continue
                pos = [p for p, _ in kept]
                if pos != sorted(pos) or len(set(pos)) != len(pos):
                    self.err(f"{where}: timepoints out of route order {pos}")
                    continue
                mins = service_minutes([t for _, t in kept])
                if mins is None or any(b - a > 1440 for a, b in zip(mins, mins[1:])):
                    self.err(f"{where}: times non-monotonic {[t for _, t in kept]}")
                    continue
                trip: dict[str, Any] = {
                    "direction": dir_key, "tier": tier, "days": list(base_days),
                    "times": [{"seq": p, "stop": dir_stop_ids[p], "time": t, "min": m}
                              for (p, t), m in zip(kept, mins)],
                }
                skip_ids = [dir_stop_ids[positions[i]] for i in skipped_cols]
                notes = [cells[i] for i in skipped_cols]
                if flag:
                    meta = DAY_FLAGS.get(flag)
                    if meta is None:
                        self.err(f"{where}: unknown day flag {flag!r}")
                        continue
                    if "days" in meta:
                        trip["days"] = list(meta["days"])
                    if "skip" in meta:
                        target = canon_norm(meta["skip"])
                        hits = [s for s in dir_stop_ids if self.stop_norm(s) == target]
                        if not hits:
                            self.err(f"{where}: flag {flag!r} but {meta['skip']!r} is not on this direction")
                        skip_ids += hits
                    notes.append(meta["note"])
                if skip_ids:
                    trip["skip_stops"] = sorted(set(skip_ids))
                if notes:
                    trip["note"] = "; ".join(dict.fromkeys(notes))
                line["trips"].append(trip)

        freq = self.frequency_services(slug, soup, slug)
        self.stop_id = register
        if freq:
            line["frequency"] = freq
        if not line["trips"] and not freq:
            self.err(f"{slug}: produced zero trips")
        return line


def build(season: str) -> tuple[dict[str, Any], list[str]]:
    if season not in SEASONS:
        raise SystemExit(f"unknown season {season!r}; add it to SEASONS with its OCCT source")
    raw_dir = ROOT / "data" / "raw" / season
    b = Builder()
    index = parse_index((raw_dir / "routeschedule.html").read_text())
    lines = []
    for slug, cfg in PAGES.items():
        page = raw_dir / f"{slug}.html"
        if not page.exists():
            b.err(f"{slug}: no snapshot {page.relative_to(ROOT)}")
            continue
        lines.append(b.build_line(slug, cfg, page.read_text(encoding="utf-8"), index.get(slug)))
    for slug in index:
        if slug not in PAGES:
            b.err(f"index lists route page {slug!r} that PAGES does not configure")

    fetched = max(p.stat().st_mtime for p in raw_dir.glob("*.html"))
    no_coord = sorted(sid for sid, s in b.stops.items() if s["lat"] is None)
    meta = dict(SEASONS[season])
    meta.update({
        "season": season,
        "fetched_at": datetime.fromtimestamp(fetched).astimezone().isoformat(timespec="seconds"),
        "built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "seasonal_lines": SEASONAL_LINES,
        "stops_missing_coords": no_coord,
    })
    return {"meta": meta, "stops": b.stops, "lines": lines}, b.errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="fall2026")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero and skip writing if any errors remain")
    args = ap.parse_args()
    dataset, errors = build(args.season)
    out = ROOT / "data" / f"occt_dataset.{args.season}.candidate.json"

    stops, lines = dataset["stops"], dataset["lines"]
    missing = dataset["meta"]["stops_missing_coords"]
    print(f"lines: {len(lines)}   stops: {len(stops)} ({len(missing)} missing coords)")
    for ln in lines:
        print(f"  {ln['id']:4} {ln['name'][:36]:36} trips={len(ln['trips']):3} "
              f"dirs=[{','.join(ln['directions'])}]"
              + (f" freq={len(ln['frequency'])}" if ln.get("frequency") else ""))
    if missing:
        print("\nSTOPS WITHOUT COORDINATES (excluded from geographic snapping):")
        for sid in missing:
            print(f"  - {sid}: {stops[sid]['name']}")
    if errors:
        print(f"\nERRORS ({len(errors)}):")
        for e in errors:
            print("  !", e)
        if args.strict:
            print("\nSTRICT: errors remain; not writing.")
            return 1
    out.write_text(json.dumps(dataset, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nwrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
