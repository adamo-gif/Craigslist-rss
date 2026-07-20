#!/usr/bin/env python3
"""
Craigslist -> RSS generator.

Craigslist no longer exposes native RSS feeds for search results, so this
script fetches your saved search page(s), extracts listing data, and writes
a standard RSS 2.0 XML file per search. Run it on a schedule (see the
included GitHub Actions workflow) and point any RSS reader at the generated
feed URL to get notified of new listings automatically.

Two extraction strategies are used, in order:
  1. The JSON-LD block Craigslist embeds in search pages (<script
     id="ld_searchpage_results">), which is structured and reliable.
  2. A DOM fallback (BeautifulSoup, css selectors) in case Craigslist
     changes their JSON-LD output.

State (which listings we've already seen, and when we first saw them) is
kept in docs/state/<slug>.json so that:
  - pubDate reflects when *you* first saw the listing (stable across runs),
  - your RSS reader can correctly tell "new since last check" apart from
    "still there from before".
"""

import json
import re
import sys
import time
import hashlib
import html
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    # Craigslist serves normal HTML to anything that looks like a real
    # browser; an explicit UA avoids being treated as a bare bones bot.
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
STATE_DIR = DOCS / "state"


def slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return s or hashlib.sha1(name.encode()).hexdigest()[:8]


def fetch(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_via_jsonld(html_text: str, base_url: str):
    """Primary strategy: read the structured JSON-LD block."""
    soup = BeautifulSoup(html_text, "html.parser")
    tag = soup.find("script", id="ld_searchpage_results")
    if not tag or not tag.string:
        return None

    try:
        data = json.loads(tag.string)
    except json.JSONDecodeError:
        return None

    items = data.get("itemListElement") or []
    if not items:
        return None

    # Detail-page hrefs appear in the DOM in the same order as the
    # JSON-LD items; pair them by index so we get a real link per item.
    hrefs = [
        a["href"]
        for a in soup.select('a[href*="/d/"]')
        if a.get("href") and "/d/" in a["href"]
    ]

    listings = []
    for i, entry in enumerate(items):
        item = entry.get("item", entry)
        title = item.get("name") or "(untitled listing)"
        offer = item.get("offers") or {}
        price = offer.get("price")
        currency = offer.get("priceCurrency", "USD")
        area = (item.get("areaServed") or {}).get("name") if isinstance(
            item.get("areaServed"), dict
        ) else None

        link = None
        if i < len(hrefs):
            link = urljoin(base_url, hrefs[i])
        if not link:
            link = item.get("url")
        if not link:
            continue

        price_str = f"${price} {currency}".strip() if price else ""
        listings.append(
            {
                "title": title,
                "link": link,
                "price": price_str,
                "location": area or "",
            }
        )
    return listings or None


def parse_via_dom_fallback(html_text: str, base_url: str):
    """Backup strategy if Craigslist changes their JSON-LD output."""
    soup = BeautifulSoup(html_text, "html.parser")
    rows = soup.select("li.cl-search-result, div.cl-search-result")
    listings = []
    for row in rows:
        link_tag = row.select_one("a.cl-app-anchor, a[href*='/d/']")
        if not link_tag or not link_tag.get("href"):
            continue
        title_tag = row.select_one(".title, .label")
        price_tag = row.select_one(".price")
        loc_tag = row.select_one(".location")
        listings.append(
            {
                "title": (title_tag.get_text(strip=True) if title_tag
                          else link_tag.get_text(strip=True)) or "(untitled listing)",
                "link": urljoin(base_url, link_tag["href"]),
                "price": price_tag.get_text(strip=True) if price_tag else "",
                "location": loc_tag.get_text(strip=True) if loc_tag else "",
            }
        )
    return listings or None


def scrape_search(url: str):
    text = fetch(url)
    listings = parse_via_jsonld(text, url)
    if listings is None:
        listings = parse_via_dom_fallback(text, url)
    return listings or []


def load_state(slug: str) -> dict:
    path = STATE_DIR / f"{slug}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(slug: str, state: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / f"{slug}.json").write_text(json.dumps(state, indent=2))


def rfc822(dt: datetime) -> str:
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


def build_rss(feed_name: str, feed_url: str, listings: list, state: dict,
              max_age_days: int, max_items: int) -> str:
    now = datetime.now(timezone.utc)
    cutoff = now.timestamp() - max_age_days * 86400

    # Update state: record first-seen time for new links.
    for item in listings:
        if item["link"] not in state:
            state[item["link"]] = now.isoformat()

    # Drop stale entries from state so the file doesn't grow forever.
    state = {
        link: ts for link, ts in state.items()
        if datetime.fromisoformat(ts).timestamp() >= cutoff
    }

    # Sort newest-first by first-seen time, cap length.
    enriched = []
    for item in listings:
        seen_iso = state.get(item["link"])
        if not seen_iso:
            continue
        enriched.append((datetime.fromisoformat(seen_iso), item))
    enriched.sort(key=lambda pair: pair[0], reverse=True)
    enriched = enriched[:max_items]

    items_xml = []
    for seen_dt, item in enriched:
        title = html.escape(f"{item['title']} {item['price']}".strip())
        desc = html.escape(f"{item['location']} {item['price']}".strip())
        guid = html.escape(item["link"])
        items_xml.append(f"""    <item>
      <title>{title}</title>
      <link>{guid}</link>
      <guid isPermaLink="true">{guid}</guid>
      <description>{desc}</description>
      <pubDate>{rfc822(seen_dt.astimezone(timezone.utc))}</pubDate>
    </item>""")

    channel_title = html.escape(feed_name)
    channel_link = html.escape(feed_url)
    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{channel_title}</title>
    <link>{channel_link}</link>
    <description>Craigslist listings matching: {channel_title}</description>
    <lastBuildDate>{rfc822(now)}</lastBuildDate>
{chr(10).join(items_xml)}
  </channel>
</rss>
"""
    return rss, state


def main():
    config = json.loads((ROOT / "config.json").read_text())
    max_age_days = config.get("max_age_days", 14)
    max_items = config.get("max_items_per_feed", 100)

    DOCS.mkdir(parents=True, exist_ok=True)
    index_entries = []

    for feed in config["feeds"]:
        name = feed["name"]
        url = feed["url"]
        slug = slugify(name)
        print(f"Fetching: {name} -> {url}", file=sys.stderr)

        try:
            listings = scrape_search(url)
        except requests.RequestException as e:
            print(f"  ERROR fetching {url}: {e}", file=sys.stderr)
            listings = []

        print(f"  found {len(listings)} listings", file=sys.stderr)

        state = load_state(slug)
        rss_xml, new_state = build_rss(
            name, url, listings, state, max_age_days, max_items
        )
        save_state(slug, new_state)

        out_path = DOCS / f"{slug}.xml"
        out_path.write_text(rss_xml)
        index_entries.append((name, f"{slug}.xml"))

        time.sleep(2)  # be polite between requests

    # Simple index page linking every feed, handy once you're hosting
    # via GitHub Pages.
    links = "\n".join(
        f'    <li><a href="{path}">{html.escape(name)}</a> '
        f'&mdash; <code>{path}</code></li>'
        for name, path in index_entries
    )
    index_html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Craigslist RSS feeds</title></head>
<body>
  <h1>Craigslist RSS feeds</h1>
  <p>Last updated: {datetime.now(timezone.utc).isoformat()}</p>
  <ul>
{links}
  </ul>
</body></html>
"""
    (DOCS / "index.html").write_text(index_html)
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
