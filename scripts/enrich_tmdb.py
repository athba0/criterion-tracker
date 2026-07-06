#!/usr/bin/env python3
"""Enrich films with TMDB data — English + Arabic overviews, TMDB id, poster.

Match strategy: exact via IMDb id (/find) when we have one, else title+year
search. Overviews come from /movie/{id}?append_to_response=translations, so we
get the English overview and every localized (incl. Arabic) overview in one call.

Keys are read from secrets.local.json (gitignored) or the TMDB_TOKEN env var —
nothing secret is ever written into the output. Writes data/tmdb.json:
    {"Title|Year": {"tmdb_id", "overview_en", "overview_ar", "poster_path"}}
Resumable: films already present are skipped.
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "tmdb.json"
API = "https://api.themoviedb.org/3"

sec = {}
sfile = ROOT / "secrets.local.json"
if sfile.exists():
    sec = json.loads(sfile.read_text())
TOKEN = os.environ.get("TMDB_TOKEN") or sec.get("tmdb_read_token")
if not TOKEN:
    raise SystemExit("No TMDB token (set TMDB_TOKEN or secrets.local.json)")
HDR = {"Authorization": "Bearer " + TOKEN, "accept": "application/json"}

films = json.loads((ROOT / "data" / "films_ranked.json").read_text())
data = json.loads(OUT.read_text()) if OUT.exists() else {}


def key(f):
    return f"{f['title']}|{f['year']}"


def get(path, **params):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            ra = e.headers.get("Retry-After") if e.headers else None
            wait = int(ra) if ra and ra.isdigit() else 2 * (attempt + 1)
            time.sleep(min(wait, 30))
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None


def find_tmdb_id(f):
    if f.get("imdb_id"):
        d = get(f"/find/{f['imdb_id']}", external_source="imdb_id")
        if d and d.get("movie_results"):
            return d["movie_results"][0]["id"]
    # fall back to a title+year search
    d = get("/search/movie", query=f["title"], year=f["year"] or "",
            include_adult="false")
    if d and d.get("results"):
        # prefer an exact-year hit
        exact = [r for r in d["results"]
                 if (r.get("release_date") or "")[:4] == str(f["year"])]
        return (exact or d["results"])[0]["id"]
    return None


def pick_ar(translations):
    """Return the longest non-empty Arabic overview across ar-* locales."""
    best = ""
    for t in translations:
        if t.get("iso_639_1") == "ar":
            ov = (t.get("data") or {}).get("overview") or ""
            if len(ov) > len(best):
                best = ov
    return best.strip() or None


done = matched = ar_count = 0
todo = [f for f in films if key(f) not in data]
print(f"{len(todo)} films to enrich ({len(data)} cached)")

for i, f in enumerate(todo, 1):
    tid = find_tmdb_id(f)
    entry = {"tmdb_id": tid, "overview_en": None, "overview_ar": None, "poster_path": None}
    if tid:
        matched += 1
        m = get(f"/movie/{tid}", language="en-US", append_to_response="translations")
        if m:
            entry["overview_en"] = (m.get("overview") or "").strip() or None
            entry["poster_path"] = m.get("poster_path")
            trans = (m.get("translations") or {}).get("translations") or []
            entry["overview_ar"] = pick_ar(trans)
            if entry["overview_ar"]:
                ar_count += 1
    data[key(f)] = entry
    done += 1
    if done % 25 == 0:
        OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False))
        print(f"[{i}/{len(todo)}] matched={matched} arabic={ar_count}", flush=True)
    time.sleep(0.08)

OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False))
tot = len(data)
m_tot = sum(1 for v in data.values() if v.get("tmdb_id"))
en_tot = sum(1 for v in data.values() if v.get("overview_en"))
ar_tot = sum(1 for v in data.values() if v.get("overview_ar"))
print(f"DONE: {tot} films, {m_tot} matched, {en_tot} EN overviews, {ar_tot} AR overviews")
