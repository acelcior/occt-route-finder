"""Detect OCCT schedule changes against the committed raw snapshot.

    python scripts/check_for_updates.py --season fall2026            # report only
    python scripts/check_for_updates.py --season fall2026 --write    # also refresh data/raw/<season>/

Fetches the route index and every route page (politely: sequential, 1 s apart),
reduces each page to its *schedule content* — stop lists, table ids, headers and
rows — and diffs that against the snapshot, so cosmetic markup changes do not
trigger. Exit status: 0 unchanged, 1 schedule content changed, 2 fetch error.
The News & Info page is checked too but only reported (it changes often).
"""

from __future__ import annotations

import argparse
import difflib
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from scrape_schedules import BASE, INDEX_URL, REQUEST_DELAY_S, fetch, parse_index  # noqa: E402

NEWS_URL = BASE + "news.html"


def schedule_content(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[str] = []
    for blk in soup.select(".stop-scroll"):
        out.append("STOPS " + " | ".join(e.get_text(" ", strip=True) for e in blk.select(".stop-name")))
    for t in soup.select("table.sched-table"):
        wid = next((a["id"] for a in t.parents if a.has_attr("id")), "?")
        out.append(f"TABLE {wid} " + " | ".join(th.get_text(" ", strip=True) for th in t.select("thead th")))
        for tr in t.select("tbody tr"):
            out.append("  " + " | ".join(td.get_text(" ", strip=True) for td in tr.select("td")))
    # service-hours / notice text that carries meaning but lives outside tables
    text = " ".join(soup.get_text(" ").split())
    for key in ("Operating Times", "Passenger Notices"):
        i = text.find(key)
        if i >= 0:
            out.append(f"TEXT {key}: {text[i:i + 400]}")
    return out


def news_text(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    return [" ".join(soup.get_text("\n").split())[:20000]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="fall2026")
    ap.add_argument("--write", action="store_true", help="refresh the snapshot with the live pages")
    args = ap.parse_args()
    raw_dir = ROOT / "data" / "raw" / args.season
    changed: list[str] = []

    try:
        index_html = fetch(INDEX_URL)
    except requests.RequestException as e:
        print(f"fetch failed: {e}")
        return 2
    live_index = parse_index(index_html)
    old_index = parse_index((raw_dir / "routeschedule.html").read_text()) if (raw_dir / "routeschedule.html").exists() else {}
    for slug in sorted(set(live_index) | set(old_index)):
        if slug not in old_index:
            print(f"NEW ROUTE PAGE: {slug} -> {live_index[slug]}")
            changed.append(slug)
        elif slug not in live_index:
            print(f"ROUTE PAGE REMOVED: {slug}")
            changed.append(slug)

    pages = {"routeschedule": index_html}
    for slug, url in live_index.items():
        time.sleep(REQUEST_DELAY_S)
        try:
            pages[slug] = fetch(url)
        except requests.RequestException as e:
            print(f"fetch failed for {slug}: {e}")
            return 2

    for slug, html in pages.items():
        old = raw_dir / f"{slug}.html"
        if not old.exists():
            continue
        diff = list(difflib.unified_diff(schedule_content(old.read_text()), schedule_content(html),
                                         fromfile=f"snapshot/{slug}", tofile=f"live/{slug}", lineterm="", n=0))
        if diff:
            changed.append(slug)
            print(f"\n=== {slug}: schedule content changed ===")
            print("\n".join(diff[:80]))

    try:
        time.sleep(REQUEST_DELAY_S)
        news = fetch(NEWS_URL)
        news_file = raw_dir / "news.html"
        if news_file.exists() and news_text(news_file.read_text()) != news_text(news):
            print("\nNOTE: OCCT News & Info page changed — check for service notices (holidays, detours, Late Nite).")
        if args.write:
            news_file.write_text(news, encoding="utf-8")
    except requests.RequestException as e:
        print(f"news fetch failed (ignored): {e}")

    if args.write:
        raw_dir.mkdir(parents=True, exist_ok=True)
        for slug, html in pages.items():
            (raw_dir / f"{slug}.html").write_text(html, encoding="utf-8")
        print(f"\nsnapshot refreshed in {raw_dir.relative_to(ROOT)}")

    if changed:
        print(f"\nCHANGED: {', '.join(sorted(set(changed)))}")
        return 1
    print("\nno schedule changes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
