"""Normalize OCCT stop names for matching cache ↔ routes ↔ user input."""

from __future__ import annotations

import json
import re
from pathlib import Path

# Word-level abbreviation → canonical token (lowercase)
_ABBREV = {
    "st": "street",
    "street": "street",
    "av": "avenue",
    "ave": "avenue",
    "avenue": "avenue",
    "rd": "road",
    "road": "road",
    "dr": "drive",
    "drive": "drive",
    "blvd": "boulevard",
    "boulevard": "boulevard",
    "pl": "place",
    "place": "place",
    "pkwy": "parkway",
    "parkway": "parkway",
}


def normalize_stop_name(name: str) -> str:
    s = name.strip().lower()
    s = s.replace("&", " and ")
    s = s.replace("/", " ")
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""
    out: list[str] = []
    for w in s.split():
        out.append(_ABBREV.get(w, w))
    return " ".join(out)


def load_stop_cache_coords(
    path: Path | None = None,
) -> dict[str, dict[str, float]]:
    if path is None:
        path = Path(__file__).resolve().parent.parent / "data" / "stop_cache.json"
    with path.open(encoding="utf-8") as f:
        raw: dict[str, dict[str, float]] = json.load(f)
    return raw


def build_norm_to_canonical(cache: dict[str, dict[str, float]]) -> dict[str, str]:
    """One canonical string per normalized form (lexicographically first key wins)."""
    groups: dict[str, list[str]] = {}
    for k in cache:
        n = normalize_stop_name(k)
        if not n:
            continue
        groups.setdefault(n, []).append(k)
    return {n: sorted(keys)[0] for n, keys in groups.items()}


# Short typing aliases → expand before normalization / cache lookup
_INPUT_ALIASES: dict[str, str] = {
    "uu": "University Union",
    "student union": "University Union",
    "the union": "University Union",
    "union university": "University Union",
}


def coords_for_input(
    raw: str,
    cache: dict[str, dict[str, float]],
    norm_to_canonical: dict[str, str],
) -> tuple[float, float] | None:
    """Resolve trimmed user/stop string to lat/lon using normalized cache lookup."""
    low = raw.strip().lower()
    if low in _INPUT_ALIASES:
        raw = _INPUT_ALIASES[low]
    key = normalize_stop_name(raw)
    if not key:
        return None
    if key in norm_to_canonical:
        canon = norm_to_canonical[key]
        loc = cache.get(canon)
        if loc:
            return float(loc["lat"]), float(loc["lon"])
    # Direct key (exact cache key after strip)
    stripped = raw.strip()
    if stripped in cache:
        loc = cache[stripped]
        return float(loc["lat"]), float(loc["lon"])
    return None


def coords_from_routes_stops(
    raw: str,
    routes: list[dict],
) -> tuple[float, float] | None:
    """Fallback: match autocomplete / free text to any stop_coords on a route (normalized name)."""
    key = normalize_stop_name(raw)
    if not key:
        return None
    for route in routes:
        for name, loc in (route.get("stop_coords") or {}).items():
            if not loc or not isinstance(loc, dict):
                continue
            try:
                lat, lon = loc.get("lat"), loc.get("lon")
                if lat is None or lon is None:
                    continue
            except (TypeError, AttributeError):
                continue
            if normalize_stop_name(name) == key:
                return float(lat), float(lon)
    return None
