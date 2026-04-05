import json
import requests
from datetime import datetime
from math import radians, sin, cos, sqrt, atan2

# -----------------------------
# LOAD DATA
# -----------------------------
with open("occt_routes_geo.json") as f:
    routes = json.load(f)

# -----------------------------
# CONFIG
# -----------------------------
CAMPUS_KEYWORDS = ["binghamton", "university", "bing"]
MAX_DEST_DIST = 2000

ORIGIN_STOP_OVERRIDE = {
    "Engineering Building",
    "Academic A",
    "University Union",
    "Physical Facilities",
    "Hinman",
    "Hinman / Academic A"
}

# -----------------------------
# GEOCODE
# -----------------------------
def geocode(address):
    queries = [
        f"{address}, Binghamton University, NY",
        f"{address}, Binghamton, NY",
        f"{address}, Broome County, NY"
    ]

    for q in queries:
        try:
            url = "https://nominatim.openstreetmap.org/search"
            params = {"q": q, "format": "json", "limit": 1}
            res = requests.get(url, params=params, headers={"User-Agent": "OCCTApp/6.0"})
            data = res.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
        except:
            pass

    return None

# -----------------------------
# DISTANCE
# -----------------------------
def dist(a, b):
    lat1, lon1 = a
    lat2, lon2 = b

    R = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)

    x = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return 2 * R * atan2(sqrt(x), sqrt(1-x))

# -----------------------------
# TIME
# -----------------------------
def clean_time(t):
    return ''.join([c for c in t if c.isdigit() or c in ": APMapm"])

def parse_time(t):
    try:
        return datetime.strptime(clean_time(t), "%I:%M %p")
    except:
        return None

def get_schedule(route):
    if datetime.today().weekday() < 5:
        return route["schedules"].get("weekday", [])
    else:
        return route["schedules"].get("weekend", [])

# -----------------------------
# WALK TIME
# -----------------------------
def walking_minutes(m):
    return int(m / 80)

# -----------------------------
# CORE ROUTING (NEW MODEL)
# -----------------------------
def find_routes(origin_text, dest_coord):
    options = []
    now = datetime.now()

    is_campus = any(k in origin_text.lower() for k in CAMPUS_KEYWORDS)

    for route in routes:
        route_name = route["route"].lower()

        # ✅ Prefer outbound if from campus
        if is_campus and "outbound" not in route_name:
            continue

        stops = route["stops"]
        coords = route["stop_coords"]

        # -----------------------------
        # 1. Find closest stop to destination
        # -----------------------------
        best_stop = None
        best_dist = float("inf")

        for stop in stops:
            c = coords.get(stop)
            if not c:
                continue

            d = dist(dest_coord, (c["lat"], c["lon"]))
            if d < best_dist:
                best_dist = d
                best_stop = stop

        if not best_stop or best_dist > MAX_DEST_DIST:
            continue

        dest_index = stops.index(best_stop)

        # -----------------------------
        # 2. Reverse stops (destination → origin)
        # -----------------------------
        ride_stops = stops[:dest_index+1]

        # -----------------------------
        # 3. Choose boarding stop
        # -----------------------------
        origin_stop = ride_stops[0]

        if origin_stop in ORIGIN_STOP_OVERRIDE:
            display_origin = "University Union"
        else:
            display_origin = origin_stop

        # -----------------------------
        # 4. Find best time (optional)
        # -----------------------------
        schedule = get_schedule(route)

        depart, arrive = None, None

        for trip in schedule:
            times = trip["stop_times"]

            if origin_stop in times and best_stop in times:
                d = parse_time(times[origin_stop])
                a = parse_time(times[best_stop])

                if d and a:
                    if not depart or (d >= now and d < depart):
                        depart, arrive = d, a

        options.append({
            "route": route["route"],
            "origin_stop": display_origin,
            "dest_stop": best_stop,
            "walk_dist": best_dist,
            "depart": depart,
            "arrive": arrive,
            "stops": ride_stops
        })

    # -----------------------------
    # SORT OPTIONS
    # -----------------------------
    options.sort(key=lambda x: (
        x["depart"] is None,
        x["depart"] if x["depart"] else datetime.max,
        x["walk_dist"]
    ))

    return options[:3]

# -----------------------------
# MAIN
# -----------------------------
def plan_trip(origin, destination):
    dest_coord = geocode(destination)

    if not dest_coord:
        return "❌ Could not geocode destination."

    routes_found = find_routes(origin, dest_coord)

    if not routes_found:
        return "❌ No routes found."

    output = []

    for i, r in enumerate(routes_found, 1):
        depart_str = r["depart"].strftime("%I:%M %p") if r["depart"] else "No upcoming time"
        arrive_str = r["arrive"].strftime("%I:%M %p") if r["arrive"] else "N/A"

        stops_list = "\n   → ".join(r["stops"])

        output.append(f"""
=========== OPTION {i} ===========

🚌 Take: {r['route']}
🚏 Board at: {r['origin_stop']}
⏰ Depart: {depart_str}

🛑 Stops:
   → {stops_list}

📍 Get off: {r['dest_stop']}
🕒 Arrive: {arrive_str}

🚶 Walk {int(r['walk_dist'])}m ({walking_minutes(r['walk_dist'])} min) to destination
""")

    return "\n".join(output)

# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    while True:
        o = input("\nFrom: ")
        d = input("To: ")
        print(plan_trip(o, d))