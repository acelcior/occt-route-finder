import json
import sqlite3
from datetime import datetime
from math import atan2, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any
from functools import lru_cache

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


DATA_PATH = Path(__file__).resolve().parent.parent / "occt_routes_geo.json"
DB_PATH = Path(__file__).resolve().parent.parent / "occt_routes.db"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_UA = "occt-vercel-planner/1.0"
MAX_STOP_DISTANCE_M = 2000


class RouteRequest(BaseModel):
    origin: str
    destination: str


app = FastAPI(title="OCCT Planner API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def init_db():
    """Initialize SQLite database from JSON if it doesn't exist."""
    if DB_PATH.exists():
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create tables
    cursor.execute('''
        CREATE TABLE routes (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            url TEXT,
            json_data TEXT NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE stops (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            lat REAL,
            lon REAL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE route_stops (
            route_id INTEGER,
            stop_id INTEGER,
            order_index INTEGER,
            FOREIGN KEY (route_id) REFERENCES routes(id),
            FOREIGN KEY (stop_id) REFERENCES stops(id)
        )
    ''')
    
    # Load from JSON
    with DATA_PATH.open("r", encoding="utf-8") as f:
        json_routes = json.load(f)
    
    for route_data in json_routes:
        route_name = route_data.get("route", "Unknown")
        route_url = route_data.get("url", "")
        
        # Insert route
        cursor.execute(
            "INSERT INTO routes (name, url, json_data) VALUES (?, ?, ?)",
            (route_name, route_url, json.dumps(route_data))
        )
        route_id = cursor.lastrowid
        
        # Insert stops
        stops = route_data.get("stops", [])
        stop_coords = route_data.get("stop_coords", {})
        
        for idx, stop_name in enumerate(stops):
            coords = stop_coords.get(stop_name, {})
            lat = coords.get("lat")
            lon = coords.get("lon")
            
            # Insert or get stop
            cursor.execute(
                "INSERT OR IGNORE INTO stops (name, lat, lon) VALUES (?, ?, ?)",
                (stop_name, lat, lon)
            )
            
            cursor.execute("SELECT id FROM stops WHERE name = ?", (stop_name,))
            stop_id = cursor.fetchone()[0]
            
            # Link route to stop
            cursor.execute(
                "INSERT INTO route_stops (route_id, stop_id, order_index) VALUES (?, ?, ?)",
                (route_id, stop_id, idx)
            )
    
    conn.commit()
    conn.close()


def get_routes_data() -> list[dict[str, Any]]:
    """Get all routes from database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT json_data FROM routes")
    routes = [json.loads(row[0]) for row in cursor.fetchall()]
    conn.close()
    return routes


def get_all_stops() -> list[str]:
    """Get all unique stop names."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM stops ORDER BY name")
    stops = [row[0] for row in cursor.fetchall()]
    conn.close()
    return stops


# Initialize database on startup
init_db()
ROUTES: list[dict[str, Any]] = get_routes_data()


@lru_cache(maxsize=128)
def geocode(address: str) -> tuple[float, float]:
    queries = [
        f"{address}, Binghamton University, NY",
        f"{address}, Binghamton, NY",
        f"{address}, Broome County, NY",
    ]
    headers = {"User-Agent": NOMINATIM_UA}

    for query in queries:
        try:
            resp = requests.get(
                NOMINATIM_URL,
                params={"q": query, "format": "jsonv2", "limit": 1},
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
        except requests.RequestException:
            continue

    raise HTTPException(status_code=404, detail=f"Could not geocode: {address}")


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = a
    lat2, lon2 = b
    r = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    x = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * r * atan2(sqrt(x), sqrt(1 - x))


def parse_time(raw: str):
    cleaned = "".join(c for c in raw if c.isdigit() or c in ": APMapm")
    try:
        return datetime.strptime(cleaned.strip(), "%I:%M %p")
    except ValueError:
        return None


def active_schedule(route: dict[str, Any]) -> list[dict[str, Any]]:
    return route.get("schedules", {}).get("weekday" if datetime.now().weekday() < 5 else "weekend", [])


def closest_stop_in_route(
    route: dict[str, Any], point: tuple[float, float]
) -> tuple[str | None, float]:
    best_stop = None
    best_dist = float("inf")
    coords = route.get("stop_coords", {})
    for stop in route.get("stops", []):
        loc = coords.get(stop)
        if not loc:
            continue
        d = distance_m(point, (float(loc["lat"]), float(loc["lon"])))
        if d < best_dist:
            best_dist = d
            best_stop = stop
    return best_stop, best_dist


def format_option(option: dict[str, Any]) -> dict[str, Any]:
    dep = option["depart"].strftime("%I:%M %p").lstrip("0") if option["depart"] else "No upcoming time"
    arr = option["arrive"].strftime("%I:%M %p").lstrip("0") if option["arrive"] else "N/A"
    
    # Calculate trip duration
    trip_duration_minutes = None
    if option["depart"] and option["arrive"]:
        trip_duration_minutes = int((option["arrive"] - option["depart"]).total_seconds() / 60)
    
    return {
        "route_name": option["route_name"],
        "boarding_stop": option["origin_stop"],
        "destination_stop": option["dest_stop"],
        "departure_time": dep,
        "arrival_time": arr,
        "trip_duration_minutes": trip_duration_minutes,
        "walk_to_stop_m": round(option["origin_walk_m"], 1),
        "walk_from_stop_m": round(option["dest_walk_m"], 1),
        "stops_between": option["stops_between"],
    }


def find_top_routes(origin: str, destination: str) -> list[dict[str, Any]]:
    now = datetime.now()
    origin_coord = geocode(origin)
    dest_coord = geocode(destination)
    options: list[dict[str, Any]] = []

    for route in ROUTES:
        stops = route.get("stops", [])
        if not stops:
            continue

        origin_stop, origin_dist = closest_stop_in_route(route, origin_coord)
        dest_stop, dest_dist = closest_stop_in_route(route, dest_coord)
        if not origin_stop or not dest_stop:
            continue
        if origin_dist > MAX_STOP_DISTANCE_M or dest_dist > MAX_STOP_DISTANCE_M:
            continue

        origin_idx = stops.index(origin_stop)
        dest_idx = stops.index(dest_stop)
        if dest_idx <= origin_idx:
            continue

        depart = None
        arrive = None
        for trip in active_schedule(route):
            times = trip.get("stop_times", {})
            dep_raw = times.get(origin_stop)
            arr_raw = times.get(dest_stop)
            if not dep_raw or not arr_raw:
                continue

            dep_dt = parse_time(dep_raw)
            arr_dt = parse_time(arr_raw)
            if not dep_dt or not arr_dt:
                continue
            if dep_dt < now:
                continue
            if depart is None or dep_dt < depart:
                depart = dep_dt
                arrive = arr_dt

        options.append(
            {
                "route_name": route.get("route", "Unknown"),
                "origin_stop": origin_stop,
                "dest_stop": dest_stop,
                "origin_walk_m": origin_dist,
                "dest_walk_m": dest_dist,
                "depart": depart,
                "arrive": arrive,
                "stops_between": stops[origin_idx + 1 : dest_idx],
            }
        )

    options.sort(
        key=lambda x: (
            x["depart"] is None,
            x["depart"] if x["depart"] else datetime.max,
            x["origin_walk_m"] + x["dest_walk_m"],
        )
    )
    return [format_option(opt) for opt in options[:3]]


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/route")
def route_plan(body: RouteRequest) -> dict[str, Any]:
    routes = find_top_routes(body.origin, body.destination)
    if not routes:
        raise HTTPException(status_code=404, detail="No valid route options found.")
    return {
        "origin": body.origin,
        "destination": body.destination,
        "options": routes,
    }


@app.get("/api/stops")
def get_stops_list() -> dict[str, list[str]]:
    """Get all available bus stops for autocomplete."""
    stops = get_all_stops()
    return {"stops": stops}

