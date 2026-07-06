#!/usr/bin/env python3
"""Add original language + top billed cast to each TMDB-matched film.

One call per film: /movie/{id}?append_to_response=credits.
Updates data/tmdb.json in place, adding to each entry:
    "lang"      : original-language ISO code (e.g. "ja")   | None
    "cast"      : up to 8 top-billed actor names           | []
    "cast_done" : True   (resume marker)
"""
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMDB = ROOT / "data" / "tmdb.json"
API = "https://api.themoviedb.org/3"

sec = json.loads((ROOT / "secrets.local.json").read_text()) if (ROOT / "secrets.local.json").exists() else {}
TOKEN = os.environ.get("TMDB_TOKEN") or sec.get("tmdb_read_token")
if not TOKEN:
    raise SystemExit("No TMDB token")
HDR = {"Authorization": "Bearer " + TOKEN, "accept": "application/json"}

films = json.loads((ROOT / "data" / "films_ranked.json").read_text())
data = json.loads(TMDB.read_text())


def key(f):
    return f"{f['title']}|{f['year']}"


def get(tid):
    url = f"{API}/movie/{tid}?append_to_response=credits"
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 * (attempt + 1))
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None


todo = [f for f in films
        if (data.get(key(f)) or {}).get("tmdb_id") and not (data.get(key(f)) or {}).get("cast_done")]
print(f"{len(todo)} films to fetch language/cast")

done = 0
for i, f in enumerate(todo, 1):
    e = data[key(f)]
    d = get(e["tmdb_id"])
    if d:
        e["lang"] = d.get("original_language")
        cast = sorted(d.get("credits", {}).get("cast", []), key=lambda c: c.get("order", 99))
        e["cast"] = [c["name"] for c in cast[:8]]
        e["cast_done"] = True
    done += 1
    if done % 50 == 0:
        TMDB.write_text(json.dumps(data, indent=1, ensure_ascii=False))
        print(f"  [{i}/{len(todo)}]", flush=True)
    time.sleep(0.05)

TMDB.write_text(json.dumps(data, indent=1, ensure_ascii=False))
lg = sum(1 for v in data.values() if v.get("lang"))
ca = sum(1 for v in data.values() if v.get("cast"))
print(f"DONE: {lg} with language, {ca} with cast")
