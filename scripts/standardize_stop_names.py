#!/usr/bin/env python3
"""Apply canonical OCCT stop names across occt_routes_geo.json (stops, stop_coords, schedules)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTES_PATH = ROOT / "data" / "occt_routes_geo.json"

# Old name -> single canonical name (must match intent in stop_cache.json where applicable)
CANONICAL: dict[str, str] = {
    "Hawley & Court Streets": "Court & Hawley Streets",
    "The Union": "University Union",
    "Union University": "University Union",
}


def rename(s: str) -> str:
    return CANONICAL.get(s, s)


def merge_stop_coords(sc: dict) -> dict:
    out: dict[str, dict] = {}
    for k, v in sc.items():
        nk = rename(k)
        if nk not in out:
            out[nk] = v
        elif v is not None and isinstance(v, dict) and v.get("lat") is not None:
            # Prefer coords that look valid if duplicate keys after rename
            if out[nk] is None or not isinstance(out[nk], dict):
                out[nk] = v
    return out


def rename_schedules(schedules: dict) -> dict:
    out = {"weekday": [], "weekend": []}
    for day in ("weekday", "weekend"):
        trips = []
        for trip in schedules.get(day) or []:
            st = trip.get("stop_times") or {}
            new_st: dict[str, str] = {}
            for k, val in st.items():
                new_st[rename(k)] = val
            trips.append({**trip, "stop_times": new_st})
        out[day] = trips
    return out


def main() -> None:
    with ROUTES_PATH.open(encoding="utf-8") as f:
        routes = json.load(f)

    for route in routes:
        route["stops"] = [rename(s) for s in route.get("stops") or []]
        route["stop_coords"] = merge_stop_coords(dict(route.get("stop_coords") or {}))
        route["schedules"] = rename_schedules(route.get("schedules") or {})

    with ROUTES_PATH.open("w", encoding="utf-8") as f:
        json.dump(routes, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote {ROUTES_PATH}")


if __name__ == "__main__":
    main()
