import json
import requests
import time
import re
import os

# Files
INPUT_JSON = "occt_routes.json"
OUTPUT_JSON = "occt_routes_geo.json"
CACHE_JSON = "stop_cache.json"

# Load routes
with open(INPUT_JSON, "r") as f:
    routes = json.load(f)

# Load cache if it exists
if os.path.exists(CACHE_JSON):
    with open(CACHE_JSON, "r") as f:
        stop_cache = json.load(f)
else:
    stop_cache = {}

# Helper: clean stop names
def clean_stop_name(name):
    name = name.replace("&", "and")
    name = re.sub(r"\bAv\b", "Avenue", name)
    name = re.sub(r"\bSt\b", "Street", name)
    name = re.sub(r"\bRd\b", "Road", name)
    name = re.sub(r"\bDr\b", "Drive", name)
    name = re.sub(r"\bBlvd\b", "Boulevard", name)
    return name

# Generate multiple query variations
def generate_queries(stop_name):
    clean_name = clean_stop_name(stop_name)
    queries = [
        f"{clean_name}, Binghamton University, Binghamton, NY",
        f"{clean_name}, Binghamton, NY",
        f"{clean_name}, Broome County, NY",
        f"{clean_name}, NY"
    ]
    return queries

# Geocode a stop with retries
def geocode_stop(stop_name):
    if stop_name in stop_cache:
        return stop_cache[stop_name]  # Already done

    for query in generate_queries(stop_name):
        try:
            url = "https://nominatim.openstreetmap.org/search"
            params = {"q": query, "format": "json", "limit": 1}
            response = requests.get(url, params=params, headers={"User-Agent": "OCCTBot/2.0"})
            data = response.json()
            if data:
                coord = {"lat": float(data[0]["lat"]), "lon": float(data[0]["lon"])}
                stop_cache[stop_name] = coord
                return coord
        except Exception as e:
            print(f"Error geocoding '{stop_name}' ({query}): {e}")
        time.sleep(1)  # Respect Nominatim rate limit

    stop_cache[stop_name] = None
    return None

# Process all routes and stops
not_found_stops = set()

for route in routes:
    print(f"\nProcessing route: {route['route']}")
    if "stop_coords" not in route:
        route["stop_coords"] = {}
    for stop in route["stops"]:
        if stop in route["stop_coords"] and route["stop_coords"][stop]:
            print(f"  🔹 {stop}: Already geocoded")
            continue
        coord = geocode_stop(stop)
        route["stop_coords"][stop] = coord
        if coord:
            print(f"  ✅ {stop}: {coord}")
        else:
            print(f"  ⚠️ {stop}: Not found")
            not_found_stops.add(stop)

        # Save cache frequently
        with open(CACHE_JSON, "w") as f:
            json.dump(stop_cache, f, indent=2)

# Manual fallback for stops not found
if not_found_stops:
    print("\n⚠️ The following stops were not automatically found:")
    for stop in sorted(not_found_stops):
        print(f"- {stop}")

    print("\nYou can manually enter lat/lon for each stop.")
    for stop in sorted(not_found_stops):
        while True:
            inp = input(f"Enter lat,lon for '{stop}' (or leave blank to skip): ").strip()
            if inp == "":
                print(f"Skipping {stop}.")
                break
            try:
                lat_str, lon_str = inp.split(",")
                coord = {"lat": float(lat_str.strip()), "lon": float(lon_str.strip())}
                stop_cache[stop] = coord
                # Add to all routes that use this stop
                for route in routes:
                    if stop in route["stops"]:
                        route["stop_coords"][stop] = coord
                break
            except Exception as e:
                print("Invalid input. Use format: lat,lon (e.g., 42.091808, -75.9745055)")

# Save final routes with coordinates
with open(OUTPUT_JSON, "w") as f:
    json.dump(routes, f, indent=2)

# Save cache
with open(CACHE_JSON, "w") as f:
    json.dump(stop_cache, f, indent=2)

print("\n✅ Done! Routes with coordinates saved as:", OUTPUT_JSON)