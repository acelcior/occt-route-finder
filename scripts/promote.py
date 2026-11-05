"""Promote a reviewed candidate dataset to the live file the API serves.

    python scripts/promote.py --season fall2026

Checks (all must pass):
* the strict build of the same season reproduces the candidate with no errors;
* every trip's times are non-decreasing with at most one midnight wrap;
* every stop has coordinates or is listed in meta.stops_missing_coords;
* data/service_calendar.json parses and covers the dataset's effective_from;
* the planner loads the candidate and answers a smoke query.

Then ``data/occt_dataset.<season>.json`` is replaced atomically (write temp, rename).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))


def validate(dataset: dict, calendar: dict) -> list[str]:
    problems: list[str] = []
    stops = dataset["stops"]
    missing = set(dataset["meta"]["stops_missing_coords"])
    for sid, s in stops.items():
        if (s.get("lat") is None) != (sid in missing):
            problems.append(f"stop {sid}: coordinate state disagrees with meta.stops_missing_coords")
    for ln in dataset["lines"]:
        for t in ln["trips"]:
            mins = [x["min"] for x in t["times"]]
            seqs = [x["seq"] for x in t["times"]]
            if seqs != sorted(seqs) or len(set(seqs)) != len(seqs):
                problems.append(f"{ln['id']}/{t['direction']}: timepoints out of order {seqs}")
            if any(b < a for a, b in zip(mins, mins[1:])) or any(b - a > 1440 for a, b in zip(mins, mins[1:])):
                problems.append(f"{ln['id']}/{t['direction']}: times not monotonic {mins}")
            if t["direction"] not in ln["directions"]:
                problems.append(f"{ln['id']}: trip references unknown direction {t['direction']}")
            for x in t["times"]:
                if x["stop"] not in stops:
                    problems.append(f"{ln['id']}: unknown stop {x['stop']}")
            if not t["days"]:
                problems.append(f"{ln['id']}/{t['direction']}: trip has no service days")
    eff = date.fromisoformat(dataset["meta"]["effective_from"])
    covered = any(date.fromisoformat(p["from"]) <= eff <= date.fromisoformat(p["to"]) for p in calendar["periods"])
    if not covered:
        problems.append(f"service_calendar.json has no period covering effective_from {eff}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="fall2026")
    ap.add_argument("--skip-rebuild", action="store_true", help="trust the candidate file as-is")
    args = ap.parse_args()
    cand = ROOT / "data" / f"occt_dataset.{args.season}.candidate.json"
    live = ROOT / "data" / f"occt_dataset.{args.season}.json"
    if not cand.exists():
        print(f"no candidate {cand.relative_to(ROOT)}; run scripts/build_dataset.py --season {args.season} --strict")
        return 1

    if not args.skip_rebuild:
        from build_dataset import build
        rebuilt, errors = build(args.season)
        if errors:
            print("strict build has errors; refusing to promote:")
            for e in errors:
                print("  !", e)
            return 1
        a = json.loads(cand.read_text())
        for k in ("built_at",):
            a["meta"].pop(k, None)
            rebuilt["meta"].pop(k, None)
        if a != rebuilt:
            print("candidate differs from a fresh strict build; rebuild and review again")
            return 1

    dataset = json.loads(cand.read_text())
    calendar = json.loads((ROOT / "data" / "service_calendar.json").read_text())
    problems = validate(dataset, calendar)
    if problems:
        print(f"{len(problems)} validation problem(s):")
        for p in problems:
            print("  !", p)
        return 1

    # Smoke-test the planner against the candidate in a temp data dir.
    from planner import Planner, TZ
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        for name in ("service_calendar.json", "overrides.json", "places.json", "stop_cache.json"):
            src = ROOT / "data" / name
            if src.exists():
                (tdp / name).write_text(src.read_text())
        (tdp / f"occt_dataset.{args.season}.json").write_text(cand.read_text())
        pl = Planner(tdp)
        union = pl.resolve_place("University Union")
        udc = pl.resolve_place("University Downtown Center")
        assert union and udc, "smoke: core stops must resolve"
        when = datetime(date.fromisoformat(dataset["meta"]["effective_from"]).year, 11, 4, 10, 0, tzinfo=TZ)
        res = pl.plan(union[0], udc[0], when=when)
        assert res["journeys"], f"smoke: no journeys Union -> UDC on {when}: {res['message']}"

    tmp = live.with_suffix(".tmp")
    tmp.write_text(cand.read_text())
    os.replace(tmp, live)
    print(f"promoted {cand.relative_to(ROOT)} -> {live.relative_to(ROOT)}")
    print(f"  {len(dataset['lines'])} lines, {len(dataset['stops'])} stops, "
          f"{sum(len(l['trips']) for l in dataset['lines'])} trips, effective from {dataset['meta']['effective_from']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
