"""OCCT Planner API (FastAPI on Vercel).

Endpoints
---------
POST /api/route   {origin, destination, mode?: now|depart|arrive, when?: ISO local time, access_m?}
GET  /api/route   same as query parameters (shareable links)
GET  /api/meta    dataset freshness, today's service profile, alerts
GET  /api/stops   names for autocomplete (stops + campus places)
GET  /api/health

Geocoding order: known stop / place names → Google (if GOOGLE_API_KEY) → Nominatim,
all bounded to the OCCT service area. External lookups are cached per serverless
instance (lru_cache is process-local; that is fine at this scale).
"""

from __future__ import annotations

import os
import sys
import threading
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import requests
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "src"))
from planner import DEFAULT_ACCESS_M, MAX_ACCESS_M, TZ, Planner  # noqa: E402

PLANNER = Planner(_ROOT / "data")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_UA = "occt-route-finder/2.0 (trip planner; contact severesalt@gmail.com)"
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
# Broome County-ish box: results outside it are rejected rather than routed to nothing.
BBOX = {"lat_min": 41.95, "lat_max": 42.30, "lon_min": -76.20, "lon_max": -75.70}
_NOMINATIM_LOCK = threading.Lock()
_NOMINATIM_LAST = 0.0

app = FastAPI(title="OCCT Planner API")


class RouteRequest(BaseModel):
    origin: str = Field(min_length=1, max_length=120)
    destination: str = Field(min_length=1, max_length=120)
    mode: Literal["now", "depart", "arrive"] = "now"
    when: str | None = Field(default=None, max_length=40, description="ISO local date-time, e.g. 2026-11-06T23:40")
    access_m: float = Field(default=DEFAULT_ACCESS_M, ge=100, le=MAX_ACCESS_M)


def _in_bbox(lat: float, lon: float) -> bool:
    return BBOX["lat_min"] <= lat <= BBOX["lat_max"] and BBOX["lon_min"] <= lon <= BBOX["lon_max"]


def _google(raw: str) -> tuple[float, float] | None:
    if not GOOGLE_API_KEY:
        return None
    try:
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": f"{raw}, Binghamton, NY", "region": "us", "key": GOOGLE_API_KEY,
                    "bounds": f"{BBOX['lat_min']},{BBOX['lon_min']}|{BBOX['lat_max']},{BBOX['lon_max']}"},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "OK" and data.get("results"):
            loc = data["results"][0]["geometry"]["location"]
            return float(loc["lat"]), float(loc["lng"])
    except (requests.RequestException, KeyError, ValueError):
        pass
    return None


def _nominatim(raw: str) -> tuple[float, float] | None:
    global _NOMINATIM_LAST
    for q in (f"{raw}, Binghamton, NY, USA", f"{raw}, Vestal, NY, USA", f"{raw}, Broome County, NY, USA"):
        with _NOMINATIM_LOCK:  # Nominatim usage policy: at most one request per second
            wait = 1.0 - (time.monotonic() - _NOMINATIM_LAST)
            if wait > 0:
                time.sleep(wait)
            _NOMINATIM_LAST = time.monotonic()
        try:
            resp = requests.get(
                NOMINATIM_URL,
                params={"q": q, "format": "jsonv2", "limit": 1, "countrycodes": "us",
                        "viewbox": f"{BBOX['lon_min']},{BBOX['lat_max']},{BBOX['lon_max']},{BBOX['lat_min']}", "bounded": 1},
                headers={"User-Agent": NOMINATIM_UA},
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
        except (requests.RequestException, KeyError, ValueError):
            continue
    return None


@lru_cache(maxsize=256)
def geocode_external(raw: str) -> tuple[float, float] | None:
    return _google(raw) or _nominatim(raw)


def geocode(text: str) -> tuple[tuple[float, float], str]:
    """-> ((lat, lon), label). Known stop/place names never hit the network."""
    raw = text.strip().rstrip(".,;")
    if not raw:
        raise HTTPException(status_code=400, detail="Location is empty.")
    hit = PLANNER.resolve_place(raw)
    if hit:
        return hit
    coord = geocode_external(raw)
    if coord is None:
        raise HTTPException(
            status_code=404,
            detail=f"Could not find “{raw}”. Try an OCCT stop name, a campus building, or a full street "
                   f"address (e.g. 69 Court St, Binghamton, NY 13901).",
        )
    if not _in_bbox(*coord):
        raise HTTPException(status_code=404, detail=f"“{raw}” is outside the OCCT service area.")
    return coord, raw


def _parse_when(mode: str, when: str | None) -> tuple[datetime | None, str]:
    if mode == "now" or not when:
        return None, "depart"
    try:
        dt = datetime.fromisoformat(when)
    except ValueError:
        raise HTTPException(status_code=400, detail="`when` must be an ISO date-time like 2026-11-06T23:40.")
    dt = dt.replace(tzinfo=TZ) if dt.tzinfo is None else dt.astimezone(TZ)
    return dt, mode


def plan_route(req: RouteRequest) -> dict[str, Any]:
    o_coord, o_label = geocode(req.origin)
    d_coord, d_label = geocode(req.destination)
    when, mode = _parse_when(req.mode, req.when)
    result = PLANNER.plan(o_coord, d_coord, when=when, mode=mode, access_m=req.access_m,
                          origin_label=o_label, destination_label=d_label)
    result["origin"] = {"input": req.origin, "resolved": o_label, "lat": o_coord[0], "lon": o_coord[1]}
    result["destination"] = {"input": req.destination, "resolved": d_label, "lat": d_coord[0], "lon": d_coord[1]}
    return result


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/meta")
def meta() -> dict[str, Any]:
    return PLANNER.meta()


@app.post("/api/route")
def route_post(body: RouteRequest) -> dict[str, Any]:
    return plan_route(body)


@app.get("/api/route")
def route_get(
    origin: str = Query(alias="from", min_length=1, max_length=120),
    destination: str = Query(alias="to", min_length=1, max_length=120),
    mode: Literal["now", "depart", "arrive"] = "now",
    when: str | None = Query(default=None, max_length=40),
    access_m: float = Query(default=DEFAULT_ACCESS_M, ge=100, le=MAX_ACCESS_M),
) -> dict[str, Any]:
    return plan_route(RouteRequest(origin=origin, destination=destination, mode=mode, when=when, access_m=access_m))


@app.get("/api/stops")
def stops() -> dict[str, list[str]]:
    return {"stops": PLANNER.suggestions}


if os.getenv("OCCT_SERVE_STATIC"):  # local dev only; on Vercel the static build serves public/
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_ROOT / "public"), html=True), name="static")
