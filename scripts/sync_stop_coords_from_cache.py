#!/usr/bin/env python3
"""
Apply data/stop_cache.json coordinates and canonical names to occt_routes_geo.json.
Matches by normalize_stop_name(); renames stops + schedule keys for consistency.
Does not remove stops or change time strings.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from stop_names import (  # noqa: E402
    build_norm_to_canonical,
    load_stop_cache_coords,
    normalize_stop_name,
)


def collect_stop_name_strings(route: dict) -> set[str]:
    out: set[str] = set()
    for s in route.get("stops") or []:
        out.add(s)
    for k in route.get("stop_coords") or {}:
        out.add(k)
    for day in ("weekday", "weekend"):
        for trip in (route.get("schedules") or {}).get(day) or []:
            for k in (trip.get("stop_times") or {}).keys():
                out.add(k)
    return out


def rename_schedules(schedules: dict, rmap: dict[str, str]) -> dict:
    out = {"weekday": [], "weekend": []}
    for day in ("weekday", "weekend"):
        trips = []
        for trip in schedules.get(day) or []:
            st = trip.get("stop_times") or {}
            new_st = {rmap.get(k, k): v for k, v in st.items()}
            trips.append({**trip, "stop_times": new_st})
        out[day] = trips
    return out


def main() -> None:
    cache_path = ROOT / "data" / "stop_cache.json"
    routes_path = ROOT / "data" / "occt_routes_geo.json"

    cache = load_stop_cache_coords(cache_path)
    norm_to_canonical = build_norm_to_canonical(cache)

    def canonical_for(name: str) -> str | None:
        n = normalize_stop_name(name)
        if not n:
            return None
        return norm_to_canonical.get(n)

    with routes_path.open(encoding="utf-8") as f:
        routes = json.load(f)

    for route in routes:
        names = collect_stop_name_strings(route)
        rmap: dict[str, str] = {}
        for name in names:
            c = canonical_for(name)
            if c is not None:
                rmap[name] = c
            else:
                rmap[name] = name

        # stops array
        route["stops"] = [rmap[s] for s in route.get("stops") or []]

        # stop_coords: merge coords from cache when matched
        old_sc = dict(route.get("stop_coords") or {})
        canon_keys: set[str] = {rmap.get(k, k) for k in old_sc}
        new_sc: dict[str, dict[str, float]] = {}
        for canon in sorted(canon_keys):
            if canon in cache:
                new_sc[canon] = {
                    "lat": float(cache[canon]["lat"]),
                    "lon": float(cache[canon]["lon"]),
                }
            else:
                for old_k, old_loc in old_sc.items():
                    if rmap.get(old_k, old_k) == canon:
                        if old_loc is None:
                            new_sc[canon] = None
                        else:
                            new_sc[canon] = {
                                "lat": float(old_loc["lat"]),
                                "lon": float(old_loc["lon"]),
                            }
                        break
        route["stop_coords"] = new_sc

        sched = route.get("schedules") or {}
        route["schedules"] = rename_schedules(sched, rmap)

    with routes_path.open("w", encoding="utf-8") as f:
        json.dump(routes, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Updated {routes_path} from {cache_path}")


if __name__ == "__main__":
    main()
