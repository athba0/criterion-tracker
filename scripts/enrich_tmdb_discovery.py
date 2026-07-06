#!/usr/bin/env python3
"""Add TMDB keywords, collection (series/trilogy), and user reviews.

One call per film: /movie/{id}?append_to_response=keywords,reviews.
 - keywords + collection go into data/tmdb.json (small, ship in films.json)
 - reviews go into data/reviews.json (bulky, lazy-loaded by the site)
Resumable via the "disc_done" marker on each tmdb.json entry.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMDB = ROOT / "data" / "tmdb.json"
REVIEWS = ROOT / "data" / "reviews.json"
API = "https://api.themoviedb.org/3"

sec = json.loads((ROOT / "secrets.local.json").read_text()) if (ROOT / "secrets.local.json").exists() else {}
TOKEN = os.environ.get("TMDB_TOKEN") or sec.get("tmdb_read_token")
if not TOKEN:
    raise SystemExit("No TMDB token")
HDR = {"Authorization": "Bearer " + TOKEN, "accept": "application/json"}

films = json.loads((ROOT / "data" / "films_ranked.json").read_text())
data = json.loads(TMDB.read_text())
reviews = json.loads(REVIEWS.read_text()) if REVIEWS.exists() else {}


def key(f):
    return f"{f['title']}|{f['year']}"


def get(tid):
    url = f"{API}/movie/{tid}?append_to_response=keywords,reviews"
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=25) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 * (attempt + 1))
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None


def clean(text, limit=600):
    text = re.sub(r"\r\n|\r", "\n", text or "").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip() + "…"
    return text


todo = [f for f in films
        if (data.get(key(f)) or {}).get("tmdb_id") and not (data.get(key(f)) or {}).get("disc_done")]
print(f"{len(todo)} films to fetch keywords/collection/reviews")

done = kw_n = col_n = rev_n = 0
for i, f in enumerate(todo, 1):
    e = data[key(f)]
    d = get(e["tmdb_id"])
    if d:
        e["keywords"] = [k["name"] for k in d.get("keywords", {}).get("keywords", [])][:12]
        col = d.get("belongs_to_collection") or {}
        e["collection"] = col.get("name")
        e["collection_id"] = col.get("id")
        e["disc_done"] = True
        kw_n += bool(e["keywords"]); col_n += bool(e["collection"])
        revs = []
        for r in d.get("reviews", {}).get("results", [])[:3]:
            c = clean(r.get("content", ""))
            if len(c) < 20:
                continue
            revs.append({
                "author": r.get("author") or "Anonymous",
                "content": c,
                "rating": (r.get("author_details") or {}).get("rating"),
                "url": r.get("url"),
            })
        if revs:
            reviews[key(f)] = revs
            rev_n += 1
    done += 1
    if done % 50 == 0:
        TMDB.write_text(json.dumps(data, indent=1, ensure_ascii=False))
        REVIEWS.write_text(json.dumps(reviews, ensure_ascii=False, separators=(",", ":")))
        print(f"  [{i}/{len(todo)}] kw={kw_n} collections={col_n} reviewed={rev_n}", flush=True)
    time.sleep(0.05)

TMDB.write_text(json.dumps(data, indent=1, ensure_ascii=False))
REVIEWS.write_text(json.dumps(reviews, ensure_ascii=False, separators=(",", ":")))
kt = sum(1 for v in data.values() if v.get("keywords"))
ct = sum(1 for v in data.values() if v.get("collection"))
print(f"DONE: {kt} with keywords, {ct} in a collection, {len(reviews)} films with reviews")
