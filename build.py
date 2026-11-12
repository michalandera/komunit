#!/usr/bin/env python3
"""Loads the latest episodes from YouTube (and Spotify, when its RSS feed is set), writes them into
index.html, then wraps index.html in a full HTML document as dist/index.html, ready to upload to komunit.cz.

  python3 build.py            fetch episodes, then build
  python3 build.py --offline  build only, keep the episodes already in index.html
"""
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

# YouTube playlist with the episodes (the part after list= in the playlist link).
YOUTUBE_PLAYLIST_ID = "PLUQLju4iFwrI"
# RSS feed from Spotify for Creators (Settings → Availability → RSS distribution). Leave empty if not used.
# It adds the episode length and episodes that are only on Spotify.
SPOTIFY_RSS = "https://anchor.fm/s/1197614ec/podcast/rss"

ROOT = Path(__file__).parent
PAGE = ROOT / "index.html"
EXTRAS = ROOT / "episodes.json"  # hand-written additions per episode title: guest, length, spotify
MARK = re.compile(r"/\* EPISODES:START \*/.*?/\* EPISODES:END \*/", re.S)

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "komunit-site-build"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return ET.fromstring(r.read())


def key(title):
    return re.sub(r"\W+", " ", title).strip().casefold()


def minutes(duration):
    """itunes:duration is seconds or [HH:]MM:SS."""
    if not duration:
        return ""
    parts = [int(p) for p in duration.strip().split(":") if p.isdigit()]
    secs = 0
    for p in parts:
        secs = secs * 60 + p
    return f"{round(secs / 60)} min" if secs else ""


def youtube_episodes():
    feed = fetch(f"https://www.youtube.com/feeds/videos.xml?playlist_id={YOUTUBE_PLAYLIST_ID}")
    for e in feed.findall("atom:entry", NS):
        vid = e.findtext("yt:videoId", namespaces=NS)
        yield {
            "title": e.findtext("atom:title", namespaces=NS).strip(),
            "date": e.findtext("atom:published", namespaces=NS)[:10],
            "youtube": f"https://www.youtube.com/watch?v={vid}",
        }


def spotify_episodes():
    if not SPOTIFY_RSS:
        return
    from email.utils import parsedate_to_datetime
    feed = fetch(SPOTIFY_RSS)
    for item in feed.iter("item"):
        yield {
            "title": item.findtext("title").strip(),
            "date": parsedate_to_datetime(item.findtext("pubDate")).strftime("%Y-%m-%d"),
            "length": minutes(item.findtext("itunes:duration", namespaces=NS)),
            "spotify": (item.findtext("link") or "").strip(),
        }


def collect():
    episodes = {}
    for source in (spotify_episodes(), youtube_episodes()):
        for ep in source:
            merged = episodes.setdefault(key(ep["title"]), {"title": ep["title"], "date": ep["date"]})
            merged["date"] = min(merged["date"], ep["date"])
            merged.update({k: v for k, v in ep.items() if k not in ("title", "date") and v})
    extras = json.loads(EXTRAS.read_text(encoding="utf-8")) if EXTRAS.exists() else {}
    extras = {key(t): v for t, v in extras.items()}

    ordered = sorted(episodes.items(), key=lambda kv: kv[1]["date"])
    out = []
    for no, (k, ep) in enumerate(ordered, 1):
        row = {"no": no, "title": ep["title"], "guest": "", "date": ep["date"], "length": ep.get("length", ""),
               "youtube": ep.get("youtube", ""), "spotify": ep.get("spotify", "")}
        row.update({f: v for f, v in extras.get(k, {}).items() if f in row})
        out.append(row)
    return list(reversed(out))  # newest first


def update_episodes():
    try:
        episodes = collect()
    except Exception as e:  # offline or a feed is down: keep what is already on the page
        print(f"Could not load episodes ({e}); keeping the current list.")
        return
    if not episodes:
        print("The feeds returned no episodes; keeping the current list.")
        return
    rows = ",\n".join("    " + json.dumps(ep, ensure_ascii=False) for ep in episodes)
    page = PAGE.read_text(encoding="utf-8")
    new = MARK.sub(lambda _: f"/* EPISODES:START */[\n{rows}\n  ]/* EPISODES:END */", page, count=1)
    if new != page:
        PAGE.write_text(new, encoding="utf-8")
    print(f"Loaded {len(episodes)} episode(s): " + "; ".join(ep["title"] for ep in episodes))


def build():
    page = PAGE.read_text(encoding="utf-8")
    head_end = page.index("</style>") + len("</style>")
    head, body = page[:head_end], page[head_end:]
    html = f"""<!doctype html>
<html lang="cs">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
{head.strip()}
</head>
<body>
{body.strip()}
</body>
</html>
"""
    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / "CNAME").write_text("komunit.cz\n", encoding="utf-8")  # used by GitHub Pages; harmless elsewhere
    for img in ROOT.glob("*.jpg"):  # photos used by the page, e.g. michal.jpg
        (out / img.name).write_bytes(img.read_bytes())
    print(f"Wrote {out / 'index.html'}")


if __name__ == "__main__":
    if "--offline" not in sys.argv:
        update_episodes()
    build()
