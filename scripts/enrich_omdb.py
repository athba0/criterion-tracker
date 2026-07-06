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
import urllib.error
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
# collect all keys (env + list + single), deduped in order — rotate across their
# separate daily quotas
KEYS = []
if os.environ.get("OMDB_KEY"):
    KEYS.append(os.environ["OMDB_KEY"])
KEYS += sec.get("omdb_keys", [])
if sec.get("omdb_key"):
    KEYS.append(sec["omdb_key"])
KEYS = list(dict.fromkeys(k for k in KEYS if k))
if not KEYS:
    raise SystemExit("No OMDb key (set OMDB_KEY or secrets.local.json)")
print(f"{len(KEYS)} OMDb key(s) available")

films = json.loads((ROOT / "data" / "films_ranked.json").read_text())
data = json.loads(OUT.read_text()) if OUT.exists() else {}

ki = 0  # index of the key currently in use


def key(f):
    return f"{f['title']}|{f['year']}"


def fetch(imdb_id):
    """Return OMDb JSON, rotating keys when one hits its daily limit.
    Returns "EXHAUSTED" when every key is used up, or None on network failure."""
    global ki
    while ki < len(KEYS):
        # NB: no tomatoes=true — RT already comes back in Ratings[], and that flag
        # makes OMDb do a slow live RT lookup that times out on obscure titles
        url = "https://www.omdbapi.com/?" + urllib.parse.urlencode(
            {"apikey": KEYS[ki], "i": imdb_id}
        )
        resp = rotate = None
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=20) as r:
                    resp = json.load(r)
                break
            except urllib.error.HTTPError as e:
                # OMDb returns 401 when a key's daily limit is spent (or invalid)
                if e.code == 401:
                    print(f"  key #{ki + 1} unauthorized (limit/invalid) — rotating", flush=True)
                    ki += 1
                    rotate = True
                    break
                time.sleep(2 * (attempt + 1))
            except Exception:
                time.sleep(2 * (attempt + 1))
        if rotate:
            continue
        if resp is None:
            return None  # network failure — skip this film, keep the key
        # some limit responses arrive as a 200 body instead of a 401
        if resp.get("Response") == "False" and "limit" in (resp.get("Error") or "").lower():
            print(f"  key #{ki + 1} hit daily limit — rotating", flush=True)
            ki += 1
            continue
        return resp
    return "EXHAUSTED"


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
cap = PER_RUN * len(KEYS)  # safety ceiling across all keys' daily quotas
print(f"{len(todo)} films to query ({len(data)} cached); this run caps at {cap}")

done = limit_hit = 0
for f in todo[:cap]:
    d = fetch(f["imdb_id"])
    if d == "EXHAUSTED":
        print("all OMDb keys hit their daily limit — resume tomorrow")
        limit_hit = 1
        break
    if not d:
        continue
    if d.get("Response") == "False":
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
