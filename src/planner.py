"""OCCT trip planner: calendar-aware RAPTOR over the normalized dataset.

Time model
----------
Everything is America/New_York wall-clock. A query works in minutes relative to
the query date's local midnight; service days before/after shift by ±1440, so a
Late Nite trip stored as ``days=["Fri"], min=1485`` (12:45 AM Saturday) is
reachable from a Friday 11:30 PM query (offset 0, t=1485) and from a Saturday
12:15 AM query (offset -1440, t=45).

shortcut: DST transition nights are treated as 24 h of wall-clock minutes, so
the repeated/skipped hour is ignored; upgrade to epoch-based times if OCCT ever
publishes service during 1–3 AM on those two nights.
"""

from __future__ import annotations

import json
import math
from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from stop_names import normalize_stop_name

TZ = ZoneInfo("America/New_York")
DAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

WALK_M_PER_MIN = 80.0
# shortcut: straight-line × 1.3 stands in for real footpaths; upgrade to a
# pedestrian router (OSRM/Valhalla) if walk estimates prove off.
WALK_DETOUR = 1.3
DEFAULT_ACCESS_M = 800.0
MAX_ACCESS_M = 2000.0
TRANSFER_WALK_M = 400.0
MIN_TRANSFER_MIN = 2
MAX_TRANSFERS = 2
MAX_WALK_ONLY_M = 2500.0
DEFAULT_SEG_MIN = 4.0
MAX_JOURNEYS = 5
INF = float("inf")

# What students type -> the stop/place it means.
SHORT_ALIASES = {
    "uu": "University Union", "the union": "University Union", "student union": "University Union",
    "union": "University Union", "union university": "University Union", "marketplace": "University Union",
    "udc": "University Downtown Center", "downtown center": "University Downtown Center",
    "downtown": "State & Hawley Streets", "state and hawley": "State & Hawley Streets",
    "itc": "Innovative Technologies Complex (ITC)", "uclub": "UClub / University Plaza",
    "u club": "UClub / University Plaza", "university plaza": "UClub / University Plaza",
    "hinman": "Hinman / Academic A", "acad a": "Hinman / Academic A", "ciw": "Appalachian Collegiate Center",
    "college in the woods": "Appalachian Collegiate Center", "library": "Bartle Library",
    "bus terminal": "Greater Binghamton Transportation Center", "arena": "Visions Memorial Arena",
    "walmart": "Walmart / Town Square Mall Stop #2", "target": "Target / Parkway Plaza",
}


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = a
    lat2, lon2 = b
    r = 6371000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(x), math.sqrt(1 - x))


def walk_minutes(meters: float) -> int:
    if meters < 20:  # the stop *is* the place
        return 0
    return max(1, round(meters * WALK_DETOUR / WALK_M_PER_MIN))


def fmt_clock(minute_of_day: int) -> str:
    h, m = divmod(int(minute_of_day) % 1440, 60)
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------
@dataclass
class Trip:
    line_id: str
    dir_key: str
    tier: str
    days: frozenset[str]
    times: list[int | None]      # per pattern position, minutes after service-day midnight
    est: list[bool]              # True where the time is interpolated, not published
    note: str | None
    skip_stops: list[str]

    @property
    def first_min(self) -> int:
        return next(t for t in self.times if t is not None)


@dataclass
class Pattern:
    line_id: str
    line_name: str
    dir_key: str
    label: str
    headsign: str
    stops: list[str]
    trips: list[Trip] = field(default_factory=list)


def dense_times(n: int, anchors: list[tuple[int, int]], skip_pos: set[int]) -> tuple[list[int | None], list[bool]]:
    """Fill every position from the published timepoints.

    Linear interpolation between anchors by position; beyond the ends, the
    neighbouring segment's pace (or DEFAULT_SEG_MIN) is extended.
    """
    anchors = sorted(anchors)
    apos = [p for p, _ in anchors]
    out: list[int | None] = [None] * n
    est = [True] * n
    for p, t in anchors:
        out[p] = t
        est[p] = False
    for i in range(n):
        if out[i] is not None:
            continue
        k = bisect_left(apos, i)
        prev = anchors[k - 1] if k > 0 else None
        nxt = anchors[k] if k < len(anchors) else None
        if prev and nxt:
            frac = (i - prev[0]) / (nxt[0] - prev[0])
            out[i] = round(prev[1] + (nxt[1] - prev[1]) * frac)
        elif prev:
            pace = DEFAULT_SEG_MIN
            if k >= 2:
                pp = anchors[k - 2]
                pace = (prev[1] - pp[1]) / (prev[0] - pp[0])
            out[i] = round(prev[1] + pace * (i - prev[0]))
        elif nxt:
            pace = DEFAULT_SEG_MIN
            if k + 1 < len(anchors):
                nn = anchors[k + 1]
                pace = (nn[1] - nxt[1]) / (nn[0] - nxt[0])
            out[i] = round(nxt[1] - pace * (nxt[0] - i))
    for p in skip_pos:
        out[p] = None
    return out, est


class Dataset:
    def __init__(self, raw: dict[str, Any]):
        self.meta = raw["meta"]
        self.stops: dict[str, dict[str, Any]] = raw["stops"]
        self.lines: list[dict[str, Any]] = raw["lines"]
        self.effective_from = date.fromisoformat(self.meta["effective_from"])
        self.effective_to = date.fromisoformat(self.meta["effective_to"]) if self.meta.get("effective_to") else None
        self.line_by_id = {ln["id"]: ln for ln in self.lines}
        self.patterns: list[Pattern] = []
        self.stop_patterns: dict[str, list[tuple[int, int]]] = {}
        self.frequency: list[dict[str, Any]] = []
        self._build_patterns()
        self._build_footpaths()

    # -- construction -----------------------------------------------------------
    def _build_patterns(self) -> None:
        for ln in self.lines:
            for dir_key, d in ln["directions"].items():
                pat = Pattern(ln["id"], ln["name"], dir_key, d.get("label", ""), d["headsign"], list(d["stops"]))
                pi = len(self.patterns)
                self.patterns.append(pat)
                for pos, sid in enumerate(pat.stops):
                    self.stop_patterns.setdefault(sid, []).append((pi, pos))
            for t in ln["trips"]:
                pat = next(p for p in self.patterns if p.line_id == ln["id"] and p.dir_key == t["direction"])
                skip = set(t.get("skip_stops", []))
                skip_pos = {i for i, s in enumerate(pat.stops) if s in skip}
                times, est = dense_times(len(pat.stops), [(x["seq"], x["min"]) for x in t["times"]], skip_pos)
                pat.trips.append(Trip(ln["id"], t["direction"], t["tier"], frozenset(t["days"]),
                                      times, est, t.get("note"), sorted(skip)))
            for f in ln.get("frequency", []):
                self.frequency.append({**f, "line_id": ln["id"], "line_name": ln["name"]})
        for pat in self.patterns:
            pat.trips.sort(key=lambda t: t.first_min)

    def _build_footpaths(self) -> None:
        self.footpaths: dict[str, list[tuple[str, int, float]]] = {}
        located = [(sid, (s["lat"], s["lon"])) for sid, s in self.stops.items() if s.get("lat") is not None]
        for i, (a, ca) in enumerate(located):
            for b, cb in located[i + 1:]:
                d = haversine_m(ca, cb)
                if d <= TRANSFER_WALK_M:
                    w = walk_minutes(d)
                    self.footpaths.setdefault(a, []).append((b, w, d))
                    self.footpaths.setdefault(b, []).append((a, w, d))

    # -- lookups ----------------------------------------------------------------
    def stop_name(self, sid: str) -> str:
        return self.stops[sid]["name"]

    def stop_coord(self, sid: str) -> tuple[float, float] | None:
        s = self.stops[sid]
        return (s["lat"], s["lon"]) if s.get("lat") is not None else None

    def nearby_stops(self, point: tuple[float, float], radius_m: float) -> dict[str, tuple[int, float]]:
        out = {}
        for sid, s in self.stops.items():
            if s.get("lat") is None:
                continue
            d = haversine_m(point, (s["lat"], s["lon"]))
            if d <= radius_m:
                out[sid] = (walk_minutes(d), d)
        return out


# ---------------------------------------------------------------------------
# Service calendar + overrides
# ---------------------------------------------------------------------------
class Calendar:
    def __init__(self, raw: dict[str, Any]):
        self.profiles = raw["profiles"]
        self.periods = sorted(
            ({**p, "from_d": date.fromisoformat(p["from"]), "to_d": date.fromisoformat(p["to"])} for p in raw["periods"]),
            key=lambda p: (p["to_d"] - p["from_d"]).days,
        )
        for p in self.periods:
            if p["to_d"] < p["from_d"]:
                raise ValueError(f"calendar period ends before it starts: {p}")
            if p["profile"] not in self.profiles:
                raise ValueError(f"calendar period uses unknown profile {p['profile']!r}")

    def lookup(self, d: date) -> dict[str, Any]:
        for p in self.periods:
            if p["from_d"] <= d <= p["to_d"]:
                return {"date": d.isoformat(), "profile": p["profile"], "status": p["status"],
                        "note": p.get("note"), "source": p.get("source")}
        return {"date": d.isoformat(), "profile": "regular", "status": "unknown",
                "note": "No OCCT service calendar entry for this date.", "source": None}

    def allows(self, d: date, line: dict[str, Any], tier: str) -> bool:
        prof = self.profiles[self.lookup(d)["profile"]]
        lines = prof["lines"]
        if lines == "regular":
            if line.get("seasonal"):
                return False
        elif line["id"] not in lines:
            return False
        return tier in prof["tiers"]

    def allows_frequency(self, d: date) -> bool:
        return bool(self.profiles[self.lookup(d)["profile"]].get("frequency"))


def active_overrides(raw: list[dict[str, Any]], d: date) -> list[dict[str, Any]]:
    return [o for o in raw if date.fromisoformat(o["from"]) <= d <= date.fromisoformat(o["to"])]


# ---------------------------------------------------------------------------
# RAPTOR
# ---------------------------------------------------------------------------
class Label:
    __slots__ = ("arr", "kind", "stop", "prev", "trip", "off", "board_pos", "alight_pos", "pattern", "walk_min", "walk_m")

    def __init__(self, arr: float, kind: str, stop: str | None, prev: "Label | None" = None, *,
                 trip: Trip | None = None, off: int = 0, board_pos: int = -1, alight_pos: int = -1,
                 pattern: int = -1, walk_min: int = 0, walk_m: float = 0.0):
        self.arr, self.kind, self.stop, self.prev = arr, kind, stop, prev
        self.trip, self.off, self.board_pos, self.alight_pos, self.pattern = trip, off, board_pos, alight_pos, pattern
        self.walk_min, self.walk_m = walk_min, walk_m

    def rides(self) -> int:
        n, l = 0, self
        while l is not None:
            n += l.kind == "ride"
            l = l.prev
        return n


class Window:
    """Trips running within the query's day window, with absolute day offsets."""

    def __init__(self, ds: Dataset, cal: Calendar, overrides: list[dict[str, Any]], base: date, offsets=(-1, 0, 1)):
        self.ds = ds
        self.active: dict[int, list[tuple[int, Trip]]] = {}
        self.closed_stops = {o["stop"] for o in overrides if o["kind"] == "close_stop"}
        cancelled = {o["line"] for o in overrides if o["kind"] == "cancel_line"}
        for off_days in offsets:
            d = base + timedelta(days=off_days)
            wd = DAY_ABBR[d.weekday()]
            for pi, pat in enumerate(ds.patterns):
                line = ds.line_by_id[pat.line_id]
                if line["id"] in cancelled:
                    continue
                for t in pat.trips:
                    if wd in t.days and cal.allows(d, line, t.tier):
                        self.active.setdefault(pi, []).append((off_days * 1440, t))
        self._by_pos: dict[tuple[int, int], tuple[list[int], list[tuple[int, Trip]]]] = {}

    def boardable(self, pi: int, pos: int) -> tuple[list[int], list[tuple[int, Trip]]]:
        key = (pi, pos)
        if key not in self._by_pos:
            stop = self.ds.patterns[pi].stops[pos]
            rows = []
            if stop not in self.closed_stops:
                for off, t in self.active.get(pi, []):
                    if t.times[pos] is not None:
                        rows.append((t.times[pos] + off, off, t))
            rows.sort(key=lambda r: r[0])
            self._by_pos[key] = ([r[0] for r in rows], [(r[1], r[2]) for r in rows])
        return self._by_pos[key]

    def earliest(self, pi: int, pos: int, need: float) -> tuple[int, int, Trip] | None:
        times, rows = self.boardable(pi, pos)
        k = bisect_left(times, need)
        if k >= len(times):
            return None
        off, t = rows[k]
        return times[k], off, t


def raptor(ds: Dataset, win: Window, access: dict[str, tuple[int, float]], egress: dict[str, tuple[int, float]],
           t0: float, max_transfers: int = MAX_TRANSFERS) -> list[Label]:
    """Earliest-arrival labels per number of rides (Pareto: fewer rides vs earlier)."""
    best: dict[str, float] = {}
    best_dest = INF
    prev: dict[str, Label] = {}
    for sid, (wmin, wm) in access.items():
        if sid in win.closed_stops:
            continue
        prev[sid] = Label(t0 + wmin, "access", sid, walk_min=wmin, walk_m=wm)
        best[sid] = prev[sid].arr
    marked = set(prev)
    results: list[Label] = []
    best_total = INF

    for _round in range(max_transfers + 1):
        cur: dict[str, Label] = dict(prev)
        queue: dict[int, int] = {}
        for sid in marked:
            for pi, pos in ds.stop_patterns.get(sid, []):
                if pi not in queue or pos < queue[pi]:
                    queue[pi] = pos
        marked = set()
        for pi, p0 in queue.items():
            if pi not in win.active:
                continue
            pat = ds.patterns[pi]
            riding: tuple[int, Trip, int, Label] | None = None   # (off, trip, board_pos, board_label)
            for pos in range(p0, len(pat.stops)):
                sid = pat.stops[pos]
                if riding is not None:
                    off, trip, bpos, blab = riding
                    t = trip.times[pos]
                    if t is not None and sid not in win.closed_stops:
                        arr = t + off
                        if arr < best.get(sid, INF) and arr < best_dest:
                            lab = Label(arr, "ride", sid, blab, trip=trip, off=off, board_pos=bpos, alight_pos=pos, pattern=pi)
                            cur[sid] = lab
                            best[sid] = arr
                            marked.add(sid)
                            if sid in egress:
                                best_dest = min(best_dest, arr + egress[sid][0])
                plab = prev.get(sid)
                if plab is not None:
                    need = plab.arr + (MIN_TRANSFER_MIN if plab.kind == "ride" else 0)
                    here = riding[1].times[pos] + riding[0] if riding and riding[1].times[pos] is not None else INF
                    if need < here:
                        found = win.earliest(pi, pos, need)
                        if found and found[0] < here:
                            riding = (found[1], found[2], pos, plab)
        for sid in list(marked):
            lab = cur[sid]
            for s2, wmin, wm in ds.footpaths.get(sid, []):
                if s2 in win.closed_stops:
                    continue
                arr = lab.arr + wmin
                if arr < best.get(s2, INF) and arr < best_dest:
                    cur[s2] = Label(arr, "walk", s2, lab, walk_min=wmin, walk_m=wm)
                    best[s2] = arr
                    marked.add(s2)
                    if s2 in egress:
                        best_dest = min(best_dest, arr + egress[s2][0])
        # best journey of this round
        cand = None
        for sid, (wmin, wm) in egress.items():
            lab = cur.get(sid)
            if lab is None or lab.kind == "access":
                continue
            total = lab.arr + wmin
            if total < best_total and (cand is None or total < cand.arr):
                cand = Label(total, "egress", None, lab, walk_min=wmin, walk_m=wm)
        if cand is not None:
            results.append(cand)
            best_total = cand.arr
        prev = cur
        if not marked:
            break
    return results


def _pareto(journeys: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop journeys another one beats or ties on departure, arrival, transfers and walking."""
    keep = []
    for a in journeys:
        dominated = any(
            b is not a
            and b["depart_min"] >= a["depart_min"] and b["arrive_min"] <= a["arrive_min"]
            and b["transfers"] <= a["transfers"] and b["walk_min"] <= a["walk_min"]
            and (b["depart_min"], b["arrive_min"], b["transfers"], b["walk_min"])
            != (a["depart_min"], a["arrive_min"], a["transfers"], a["walk_min"])
            for b in journeys
        )
        if not dominated:
            keep.append(a)
    return keep


# ---------------------------------------------------------------------------
# Planner facade
# ---------------------------------------------------------------------------
class Planner:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        files = sorted(p for p in data_dir.glob("occt_dataset.*.json") if ".candidate." not in p.name)
        if not files:
            raise FileNotFoundError(f"no promoted dataset in {data_dir} (run scripts/promote.py)")
        self.datasets = sorted((Dataset(json.loads(p.read_text())) for p in files), key=lambda d: d.effective_from)
        self.calendar = Calendar(json.loads((data_dir / "service_calendar.json").read_text()))
        ov = data_dir / "overrides.json"
        self.overrides = json.loads(ov.read_text()).get("overrides", []) if ov.exists() else []
        self.places = self._load_places()
        self._index_names()

    # -- places / name resolution -------------------------------------------------
    def _load_places(self) -> dict[str, dict[str, Any]]:
        p = self.data_dir / "places.json"
        if not p.exists():
            return {}
        return {k: v for k, v in json.loads(p.read_text()).items() if not k.startswith("_")}

    def _index_names(self) -> None:
        self.name_index: dict[str, tuple[tuple[float, float], str]] = {}
        ds = self.datasets[-1]
        for sid, s in ds.stops.items():
            if s.get("lat") is None:
                continue
            for n in [s["name"], *s.get("aliases", [])]:
                self.name_index.setdefault(normalize_stop_name(n), ((s["lat"], s["lon"]), s["name"]))
        for name, pl in self.places.items():
            for n in [name, *pl.get("aliases", [])]:
                self.name_index.setdefault(normalize_stop_name(n), ((pl["lat"], pl["lon"]), name))
        cache = self.data_dir / "stop_cache.json"
        if cache.exists():
            for n, loc in json.loads(cache.read_text()).items():
                self.name_index.setdefault(normalize_stop_name(n), ((loc["lat"], loc["lon"]), n))
        for short, full in SHORT_ALIASES.items():
            target = self.name_index.get(normalize_stop_name(full))
            if target:
                self.name_index.setdefault(normalize_stop_name(short), target)
        self.suggestions = sorted({ds.stops[s]["name"] for s in ds.stops if ds.stops[s].get("lat") is not None}
                                  | set(self.places))

    def resolve_place(self, text: str) -> tuple[tuple[float, float], str] | None:
        key = normalize_stop_name(text)
        if not key:
            return None
        if key in self.name_index:
            return self.name_index[key]
        toks = set(key.split())
        hits = {v[1]: v for k, v in self.name_index.items() if toks <= set(k.split())}
        if len(hits) == 1:
            return next(iter(hits.values()))
        return None

    # -- dataset selection -------------------------------------------------------
    def dataset_for(self, d: date) -> tuple[Dataset, list[str]]:
        warnings: list[str] = []
        fitting = [ds for ds in self.datasets if ds.effective_from <= d and (ds.effective_to is None or d <= ds.effective_to)]
        if fitting:
            return fitting[-1], warnings
        ds = self.datasets[0] if d < self.datasets[0].effective_from else self.datasets[-1]
        warnings.append(f"stale_data: no OCCT schedule covers {d.isoformat()}; showing the {ds.meta['label']} timetable.")
        return ds, warnings

    # -- public API --------------------------------------------------------------
    def meta(self, now: datetime | None = None) -> dict[str, Any]:
        now = now.astimezone(TZ) if now else datetime.now(TZ)
        ds, warnings = self.dataset_for(now.date())
        cal = self.calendar.lookup(now.date())
        alerts = [o["message"] for o in active_overrides(self.overrides, now.date())]
        return {
            "dataset": {"season": ds.meta["season"], "label": ds.meta["label"],
                        "effective_from": ds.meta["effective_from"], "effective_to": ds.meta.get("effective_to"),
                        "fetched_at": ds.meta.get("fetched_at"), "built_at": ds.meta.get("built_at"),
                        "lines": len(ds.lines), "stops": len(ds.stops)},
            "today": cal,
            "alerts": alerts,
            "warnings": warnings + self._calendar_warnings(cal),
            "server_time": now.isoformat(timespec="minutes"),
        }

    def _calendar_warnings(self, cal: dict[str, Any]) -> list[str]:
        out = []
        if cal["status"] == "provisional":
            out.append(f"provisional_calendar: {cal['note']} OCCT has not posted this notice yet — check occtransport.org/news.")
        elif cal["status"] == "unknown":
            out.append("unknown_calendar: no OCCT service calendar covers this date; the regular timetable is shown.")
        prof = self.calendar.profiles[cal["profile"]]
        if prof.get("warning"):
            out.append("alternate_schedule: " + prof["warning"])
        return out

    def plan(self, origin: tuple[float, float], destination: tuple[float, float], *,
             when: datetime | None = None, mode: str = "depart", access_m: float = DEFAULT_ACCESS_M,
             origin_label: str = "Start", destination_label: str = "Destination") -> dict[str, Any]:
        when = (when or datetime.now(TZ)).astimezone(TZ)
        base = when.date()
        t_query = when.hour * 60 + when.minute + when.second / 60
        access_m = min(max(float(access_m), 100.0), MAX_ACCESS_M)
        ds, warnings = self.dataset_for(base)
        cal = self.calendar.lookup(base)
        warnings += self._calendar_warnings(cal)
        overrides = active_overrides(self.overrides, base)
        alerts = [o["message"] for o in overrides]
        win = Window(ds, self.calendar, overrides, base)
        access = ds.nearby_stops(origin, access_m)
        egress = ds.nearby_stops(destination, access_m)
        ctx = {"ds": ds, "base": base, "origin": origin, "destination": destination,
               "origin_label": origin_label, "destination_label": destination_label}

        journeys: list[dict[str, Any]] = []
        if access and egress:
            if mode == "arrive":
                journeys = self._arrive_by(ds, win, access, egress, t_query, ctx)
            else:
                journeys = self._range(ds, win, access, egress, t_query, ctx)

        direct_m = haversine_m(origin, destination)
        if direct_m <= MAX_WALK_ONLY_M:
            wmin = walk_minutes(direct_m)
            start = t_query - wmin if mode == "arrive" else t_query
            journeys.append(self._journey([{"type": "walk", "from": origin_label, "to": destination_label,
                                            "minutes": wmin, "meters": round(direct_m)}], start, start + wmin, ctx))
        journeys = _pareto(journeys)
        journeys.sort(key=lambda j: (j["arrive_min"], j["transfers"], j["walk_min"]) if mode != "arrive"
                      else (-j["depart_min"], j["transfers"], j["walk_min"]))
        journeys = journeys[:MAX_JOURNEYS]

        untimed = self._frequency_suggestions(ds, base, t_query, access, egress) if self.calendar.allows_frequency(base) else []
        message = None if journeys else self._empty_message(ds, win, cal, base, t_query, access, egress)
        for j in journeys:
            j.pop("arrive_min", None)
            j.pop("depart_min", None)
        return {
            "query": {"mode": mode, "when": when.isoformat(timespec="minutes"), "date": base.isoformat(),
                      "access_m": access_m, "origin": origin_label, "destination": destination_label,
                      "origin_stops_nearby": len(access), "destination_stops_nearby": len(egress)},
            "service_day": cal,
            "journeys": journeys,
            "untimed_services": untimed,
            "message": message,
            "warnings": warnings,
            "alerts": alerts,
            "dataset": {"season": ds.meta["season"], "label": ds.meta["label"], "fetched_at": ds.meta.get("fetched_at")},
        }

    # -- search strategies -------------------------------------------------------
    def _range(self, ds, win, access, egress, t0, ctx) -> list[dict[str, Any]]:
        out, seen = [], set()
        t = t0
        for _ in range(MAX_JOURNEYS):
            labels = raptor(ds, win, access, egress, t)
            if not labels:
                break
            first_dep = INF
            for lab in labels:
                j = self._journey_from_label(lab, ctx)
                sig = tuple((l.get("line_id"), l.get("direction"), l.get("board", {}).get("stop_id"),
                             l.get("alight", {}).get("stop_id"), l.get("board", {}).get("min")) for l in j["legs"] if l["type"] == "ride")
                first_dep = min(first_dep, j["first_ride_min"])
                if sig not in seen:
                    seen.add(sig)
                    out.append(j)
            if first_dep == INF:
                break
            t = first_dep + 1
        return out

    def _arrive_by(self, ds, win, access, egress, t_arrive, ctx) -> list[dict[str, Any]]:
        cands: set[float] = set()
        for sid, (wmin, _) in access.items():
            for pi, pos in ds.stop_patterns.get(sid, []):
                times, _rows = win.boardable(pi, pos)
                for tt in times:
                    dep = tt - wmin
                    if t_arrive - 6 * 60 <= dep <= t_arrive:
                        cands.add(dep)
        out, seen = [], set()
        for t in sorted(cands, reverse=True)[:60]:
            for lab in raptor(ds, win, access, egress, t):
                if lab.arr <= t_arrive:
                    j = self._journey_from_label(lab, ctx)
                    sig = (j["depart_min"], j["arrive_min"], j["transfers"])
                    if sig not in seen:
                        seen.add(sig)
                        out.append(j)
            if len(out) >= 3:
                break
        return out

    # -- journey construction ----------------------------------------------------
    def _journey_from_label(self, final: Label, ctx) -> dict[str, Any]:
        ds: Dataset = ctx["ds"]
        chain: list[Label] = []
        l = final
        while l is not None:
            chain.append(l)
            l = l.prev
        chain.reverse()  # access ... egress
        legs: list[dict[str, Any]] = []
        for lab in chain:
            if lab.kind == "access":
                legs.append({"type": "walk", "from": ctx["origin_label"], "to": ds.stop_name(lab.stop), "to_stop_id": lab.stop,
                             "minutes": lab.walk_min, "meters": round(lab.walk_m)})
            elif lab.kind == "walk":
                legs.append({"type": "walk", "from": ds.stop_name(lab.prev.stop), "from_stop_id": lab.prev.stop,
                             "to": ds.stop_name(lab.stop), "to_stop_id": lab.stop,
                             "minutes": lab.walk_min, "meters": round(lab.walk_m), "transfer": True})
            elif lab.kind == "ride":
                pat = ds.patterns[lab.pattern]
                trip, off = lab.trip, lab.off
                stops = []
                for pos in range(lab.board_pos, lab.alight_pos + 1):
                    t = trip.times[pos]
                    if t is None:
                        continue
                    stops.append({"stop_id": pat.stops[pos], "name": ds.stop_name(pat.stops[pos]),
                                  "min": t + off, "time": fmt_clock(t + off), "estimated": trip.est[pos]})
                legs.append({"type": "ride", "line_id": pat.line_id, "line_name": pat.line_name,
                             "direction": pat.dir_key, "direction_label": pat.label, "headsign": pat.headsign,
                             "tier": trip.tier, "late_nite": trip.tier == "latenite",
                             "board": stops[0], "alight": stops[-1], "stops": stops,
                             "ride_minutes": stops[-1]["min"] - stops[0]["min"], "note": trip.note})
            elif lab.kind == "egress":
                legs.append({"type": "walk", "from": ds.stop_name(lab.prev.stop), "from_stop_id": lab.prev.stop,
                             "to": ctx["destination_label"], "minutes": lab.walk_min, "meters": round(lab.walk_m)})
        rides = [l for l in legs if l["type"] == "ride"]
        depart = rides[0]["board"]["min"] - legs[0]["minutes"] if legs[0]["type"] == "walk" else rides[0]["board"]["min"]
        return self._journey(legs, depart, final.arr, ctx)

    def _journey(self, legs: list[dict[str, Any]], depart_min: float, arrive_min: float, ctx) -> dict[str, Any]:
        base: date = ctx["base"]
        rides = [l for l in legs if l["type"] == "ride"]
        midnight = datetime.combine(base, datetime.min.time(), TZ)

        def stamp(m: float) -> dict[str, Any]:
            dt = midnight + timedelta(minutes=m)
            return {"iso": dt.isoformat(timespec="minutes"), "text": fmt_clock(round(m)),
                    "day": dt.strftime("%a"), "same_day": dt.date() == base}

        for l in legs:
            if l["type"] == "ride":
                for s in l["stops"]:
                    s["day"] = stamp(s["min"])["day"]
        return {
            "depart": stamp(depart_min), "arrive": stamp(arrive_min),
            "depart_min": depart_min, "arrive_min": arrive_min,
            "duration_min": round(arrive_min - depart_min),
            "transfers": max(0, len(rides) - 1),
            "walk_min": sum(l["minutes"] for l in legs if l["type"] == "walk"),
            "walk_m": sum(l["meters"] for l in legs if l["type"] == "walk"),
            "late_nite": any(l.get("late_nite") for l in rides),
            "has_estimates": any(s["estimated"] for l in rides for s in (l["board"], l["alight"])),
            "walk_only": not rides,
            "first_ride_min": rides[0]["board"]["min"] if rides else depart_min,
            "legs": legs,
        }

    # -- untimed loops & empty states ------------------------------------------
    def _frequency_suggestions(self, ds, base, t_query, access, egress) -> list[dict[str, Any]]:
        out = []
        wd = DAY_ABBR[base.weekday()]
        for f in ds.frequency:
            if wd not in f["days"] or not (f["start_min"] <= t_query <= f["end_min"]):
                continue
            a = [(w, s) for s, (w, _) in access.items() if s in f["stops"]]
            e = [(w, s) for s, (w, _) in egress.items() if s in f["stops"]]
            if not a or not e:
                continue
            board, alight = min(a)[1], min(e)[1]
            if board == alight:
                continue
            out.append({"line_id": f["line_id"], "line_name": f["line_name"], "service": f["name"],
                        "board": ds.stop_name(board), "alight": ds.stop_name(alight),
                        "hours": f"{fmt_clock(f['start_min'])}–{fmt_clock(f['end_min'])}", "days": f["days"],
                        "walk_to_min": min(a)[0], "walk_from_min": min(e)[0], "note": f["note"]})
        return out

    def _empty_message(self, ds, win, cal, base, t_query, access, egress) -> str:
        day = base.strftime("%a %b %-d")
        if not access or not egress:
            side = "start" if not access else "destination"
            return f"No OCCT stop with known coordinates within walking range of your {side}. Try a nearby stop name or widen the walking distance."
        prof = self.calendar.profiles[cal["profile"]]
        if cal["profile"] == "none":
            return f"No OCCT service on {day}: {cal['note']}"
        # look ahead up to a week for the next departure from a stop near the start
        for off in range(0, 8):
            d = base + timedelta(days=off)
            w = Window(ds, self.calendar, active_overrides(self.overrides, d), d, offsets=(0,))
            best = None
            for sid, (wmin, _) in access.items():
                for pi, pos in ds.stop_patterns.get(sid, []):
                    times, rows = w.boardable(pi, pos)
                    k = bisect_left(times, t_query + wmin if off == 0 else 0)
                    if k < len(times) and (best is None or times[k] < best[0]):
                        best = (times[k], rows[k][1], sid)
            if best:
                t, trip, sid = best
                when = f"{fmt_clock(t)} {d.strftime('%a %b %-d')}" if off else fmt_clock(t)
                line = ds.line_by_id[trip.line_id]["name"]
                lead = prof.get("empty_message") or f"No bus connects these two points on {day}."
                return f"{lead} Next departure near your start: {line} at {ds.stop_name(sid)}, {when}."
        return (prof.get("empty_message") or "No upcoming OCCT service found from stops near your start") + \
               " — nothing scheduled in the next 7 days; check occtransport.org."
