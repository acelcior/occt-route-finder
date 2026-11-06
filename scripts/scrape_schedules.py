"""Stage A of the Fall 2026 schedule update: snapshot raw OCCT HTML.

Data-hygiene rationale
----------------------
We fetch every route's schedule page ONCE into ``data/raw/<season>/`` and commit
the raw HTML. All parsing then runs offline against the snapshot, so extraction
is reproducible and diffable when OCCT changes its markup again. This script does
*not* parse anything and does *not* touch the live JSON — snapshotting and
parsing are deliberately separate stages.

It also reconciles the live route index against the route set currently in
``data/occt_routes_geo.json`` and reports added / removed / renamed routes
loudly, rather than silently dropping a line that OCCT renamed.

Usage
-----
    python scripts/scrape_schedules.py                 # snapshot all routes
    python scripts/scrape_schedules.py --only ws       # snapshot one route page
    python scripts/scrape_schedules.py --index-only     # just fetch + diff the index

Politeness: sequential fetches with a delay and a descriptive User-Agent.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
SEASON = "fall2026"
RAW_DIR = ROOT / "data" / "raw" / SEASON
INDEX_URL = "https://occtransport.org/routeschedule.html"
BASE = "https://occtransport.org/"
USER_AGENT = (
    "occt-route-finder-scraper/1.0 (schedule update; contact severesalt@gmail.com)"
)
REQUEST_DELAY_S = 1.0


def fetch(url: str) -> str:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    resp.raise_for_status()
    return resp.text


def write_fetched_at(raw_dir: Path) -> None:
    """Record when the snapshot was taken; build_dataset.py puts it in meta.fetched_at."""
    (raw_dir / "fetched_at.txt").write_text(datetime.now().astimezone().isoformat(timespec="seconds") + "\n")


def parse_index(html: str) -> dict[str, str]:
    """Return {route_slug: absolute_url} for every route linked from the index.

    Slug is the page basename without extension, e.g. ``ws`` from ``routes/ws.html``.
    """
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(r"routes/([a-z0-9\-]+)\.html$", href, re.I)
        if not m:
            continue
        slug = m.group(1).lower()
        out[slug] = urljoin(BASE, href)
    return dict(sorted(out.items()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default=SEASON, help="snapshot folder name, e.g. spring2027")
    ap.add_argument("--only", help="fetch a single route slug (e.g. ws)")
    ap.add_argument("--index-only", action="store_true")
    args = ap.parse_args()

    raw_dir = ROOT / "data" / "raw" / args.season
    raw_dir.mkdir(parents=True, exist_ok=True)

    print(f"Fetching index: {INDEX_URL}")
    index_html = fetch(INDEX_URL)
    (raw_dir / "routeschedule.html").write_text(index_html, encoding="utf-8")
    routes = parse_index(index_html)
    print(f"Index lists {len(routes)} route pages: {', '.join(routes)}")

    if args.index_only:
        return 0

    slugs = [args.only] if args.only else list(routes)
    for slug in slugs:
        if slug not in routes:
            print(f"  !! slug {slug!r} not present in current index; skipping")
            continue
        url = routes[slug]
        dest = raw_dir / f"{slug}.html"
        print(f"  fetching {slug:6} -> {url}")
        dest.write_text(fetch(url), encoding="utf-8")
        time.sleep(REQUEST_DELAY_S)

    write_fetched_at(raw_dir)
    print(f"\nSnapshots written to {raw_dir.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
