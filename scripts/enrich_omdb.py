#!/usr/bin/env python3
"""Add Rotten Tomatoes + Metacritic scores from OMDb, keyed by IMDb id.

OMDb's free tier allows 1000 requests/day, so this caps itself per run and is
resumable — re-run on the next day to finish the remainder. Stops early and
cleanly if OMDb reports the daily limit is reached.

Key from secrets.local.json (gitignored) or OMDB_KEY env var. Writes
data/omdb.json: {"Title|Year": {"rt": int|None, "metacritic": int|None}}
"""
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "omdb.json"
PER_RUN = 980  # stay under the 1000/day free limit

sec = {}
sfile = ROOT / "secrets.local.json"
if sfile.exists():
    sec = json.loads(sfile.read_text())
KEY = os.environ.get("OMDB_KEY") or sec.get("omdb_key")
if not KEY:
    raise SystemExit("No OMDb key (set OMDB_KEY or secrets.local.json)")

films = json.loads((ROOT / "data" / "films_ranked.json").read_text())
data = json.loads(OUT.read_text()) if OUT.exists() else {}


def key(f):
    return f"{f['title']}|{f['year']}"


def fetch(imdb_id):
    url = "https://www.omdbapi.com/?" + urllib.parse.urlencode(
        {"apikey": KEY, "i": imdb_id, "tomatoes": "true"}
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                return json.load(r)
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None


def parse_scores(d):
    rt = mc = None
    for rating in d.get("Ratings", []):
        if rating["Source"] == "Rotten Tomatoes":
            rt = int(rating["Value"].rstrip("%"))
        elif rating["Source"] == "Metacritic":
            mc = int(rating["Value"].split("/")[0])
    if mc is None and d.get("Metascore", "N/A") != "N/A":
        try:
            mc = int(d["Metascore"])
        except ValueError:
            pass
    return rt, mc


todo = [f for f in films if f.get("imdb_id") and key(f) not in data]
print(f"{len(todo)} films to query ({len(data)} cached); this run caps at {PER_RUN}")

done = limit_hit = 0
for f in todo[:PER_RUN]:
    d = fetch(f["imdb_id"])
    if not d:
        continue
    if d.get("Response") == "False":
        if "limit" in (d.get("Error") or "").lower():
            print("OMDb daily limit reached — stopping (resume tomorrow)")
            limit_hit = 1
            break
        data[key(f)] = {"rt": None, "metacritic": None}
        continue
    rt, mc = parse_scores(d)
    data[key(f)] = {"rt": rt, "metacritic": mc}
    done += 1
    if done % 50 == 0:
        OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False))
        print(f"  {done} this run ({len(data)} total)", flush=True)
    time.sleep(0.15)

OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False))
rt_n = sum(1 for v in data.values() if v.get("rt") is not None)
mc_n = sum(1 for v in data.values() if v.get("metacritic") is not None)
remaining = len([f for f in films if f.get("imdb_id") and key(f) not in data])
print(f"DONE: {len(data)} cached, {rt_n} with RT, {mc_n} with Metacritic")
if remaining and not limit_hit:
    print(f"{remaining} still to fetch — re-run to continue")
elif remaining:
    print(f"{remaining} remaining — re-run tomorrow (daily limit)")
