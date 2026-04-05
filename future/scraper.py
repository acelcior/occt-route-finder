import requests
from bs4 import BeautifulSoup
import json
import time
from urllib.parse import urljoin

BASE_URL = "https://occtransport.org"
HEADERS = {"User-Agent": "Mozilla/5.0"}

visited = set()

def get_soup(url):
    print(f"🌐 Fetching: {url}")
    res = requests.get(url, headers=HEADERS)
    # If 404 or other error, give up on this URL
    if res.status_code != 200:
        print(f"   ❌ HTTP {res.status_code} at {url}")
        return None
    return BeautifulSoup(res.text, "html.parser")

def is_hub_page(soup):
    # Some pages list routes as buttons → follow them
    return bool(soup.select(".routebuttons-item"))

def extract_sub_routes(soup):
    sub_links = []
    for a in soup.select(".routebuttons-item"):
        href = a.get("href") or ""
        if not href:
            continue
        if not href.startswith("http"):
            href = "/pages/routes/" + href.split("/")[-1]
        full = urljoin(BASE_URL, href)
        sub_links.append(full)
    return sub_links

def extract_stops(soup):
    return [a.get_text(strip=True) for a in soup.select(".route-stops a")]

def parse_schedule_table(table, stops):
    trips = []
    for row in table.select("tbody tr"):
        cols = [td.get_text(strip=True) for td in row.select("td")]
        if not cols:
            continue
        trip = {"stop_times": {}}
        for i, t_val in enumerate(cols):
            if i < len(stops):
                trip["stop_times"][stops[i]] = t_val
        trips.append(trip)
    return trips

def parse_schedules(soup, stops):
    schedules = {}
    # Each .content section usually has a schedule table
    for idx, section in enumerate(soup.select(".content_box .content")):
        table = section.select_one("table")
        if not table:
            continue
        label = "weekday" if idx == 0 else "weekend"
        trips = parse_schedule_table(table, stops)
        if trips:
            schedules[label] = trips
    return schedules

def parse_route(url):
    # Avoid processing the same URL twice
    if url in visited:
        return []
    visited.add(url)

    soup = get_soup(url)
    if soup is None:
        return []

    # If it’s a hub (lists multiple route links), follow links
    if is_hub_page(soup):
        out = []
        for sub in extract_sub_routes(soup):
            out.extend(parse_route(sub))
        return out

    # Otherwise it’s a normal route schedule page
    title = soup.find("h1")
    route_name = title.get_text(strip=True) if title else "Unknown"

    print(f"   🚌 Found route: {route_name}")

    stops = extract_stops(soup)
    schedules = parse_schedules(soup, stops)

    if not schedules:
        print(f"   ⚠️ (no schedule tables) skipping")
        return []

    return [{
        "route": route_name,
        "url": url,
        "stops": stops,
        "schedules": schedules
    }]

def main():
    all_routes = []

    # All the route pages you want scraped:
    urls = [
        "https://occtransport.org/pages/routeschedule.html",
        "https://occtransport.org/pages/routes/ws-out.html",
        "https://occtransport.org/pages/routes/ws-in.html",
        "https://occtransport.org/pages/routes/lnws-out.html",
        "https://occtransport.org/pages/routes/lnws-in.html",
        "https://occtransport.org/pages/routes/ms-out.html",
        "https://occtransport.org/pages/routes/ms-in.html",
        "https://occtransport.org/pages/routes/dcl-out.html",
        "https://occtransport.org/pages/routes/dcl-in.html",
        "https://occtransport.org/pages/routes/lndcl-out.html",
        "https://occtransport.org/pages/routes/lndcl-in.html",
        "https://occtransport.org/pages/routes/udc-out.html",
        "https://occtransport.org/pages/routes/udc-in.html",
        "https://occtransport.org/pages/routes/ds-out.html",
        "https://occtransport.org/pages/routes/ds-in.html",
        "https://occtransport.org/pages/routes/cs.html",
        "https://occtransport.org/pages/routes/uc.html",
        "https://occtransport.org/pages/routes/iu.html",
        "https://occtransport.org/pages/routes/vs.html",
        "https://occtransport.org/pages/routes/oc.html",
        "https://occtransport.org/pages/routes/ics.html",
        "https://occtransport.org/pages/routes/de-b1.html",
        "https://occtransport.org/pages/routes/de-a1.html",
    ]

    for i, u in enumerate(urls):
        print("\n========================================")
        print(f"[{i+1}/{len(urls)}] Processing: {u}")
        print("========================================")
        try:
            extracted = parse_route(u)
            print(f" ➕ Collected {len(extracted)} routes")
            all_routes.extend(extracted)
        except Exception as e:
            print(f"❌ Error on {u}: {e}")

        # Gentle crawl throttle
        time.sleep(0.3)

    print(f"\n📊 TOTAL ROUTES SCRAPED: {len(all_routes)}")

    with open("occt_all_routes_full.json", "w") as f:
        json.dump(all_routes, f, indent=2)

    print("✅ Written to occt_all_routes_full.json")

if __name__ == "__main__":
    main()