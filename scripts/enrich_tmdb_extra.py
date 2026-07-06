#!/usr/bin/env python3
"""Add trailers (YouTube) + Qatar watch providers to each TMDB-matched film.

One call per film: /movie/{id}?append_to_response=videos,watch/providers.
Updates data/tmdb.json in place, adding to each entry:
    "trailer"      : YouTube video key | None
    "providers_qa" : {"flatrate":[{name,logo}], "rent":[…], "buy":[…], "link"} | None
    "extra_done"   : True   (resume marker)
Keys from secrets.local.json (gitignored) or TMDB_TOKEN env var.
"""
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMDB = ROOT / "data" / "tmdb.json"
REGION = "QA"
API = "https://api.themoviedb.org/3"

sec = {}
sfile = ROOT / "secrets.local.json"
if sfile.exists():
    sec = json.loads(sfile.read_text())
TOKEN = os.environ.get("TMDB_TOKEN") or sec.get("tmdb_read_token")
if not TOKEN:
    raise SystemExit("No TMDB token")
HDR = {"Authorization": "Bearer " + TOKEN, "accept": "application/json"}

films = json.loads((ROOT / "data" / "films_ranked.json").read_text())
data = json.loads(TMDB.read_text())


def key(f):
    return f"{f['title']}|{f['year']}"


def get(tid):
    url = f"{API}/movie/{tid}?append_to_response=videos,watch/providers"
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


def pick_trailer(videos):
    yt = [v for v in videos if v.get("site") == "YouTube"]
    # official trailer > any trailer > teaser > clip
    for want in (
        lambda v: v["type"] == "Trailer" and v.get("official"),
        lambda v: v["type"] == "Trailer",
        lambda v: v["type"] == "Teaser",
        lambda v: True,
    ):
        hit = [v for v in yt if want(v)]
        if hit:
            return hit[0]["key"]
    return None


def providers(res):
    qa = res.get(REGION)
    if not qa:
        return None
    out = {"link": qa.get("link")}
    for kind in ("flatrate", "rent", "buy"):
        if qa.get(kind):
            out[kind] = [
                {"name": p["provider_name"], "logo": p.get("logo_path")}
                for p in sorted(qa[kind], key=lambda p: p.get("display_priority", 99))
            ]
    return out


todo = [f for f in films
        if (data.get(key(f)) or {}).get("tmdb_id") and not (data.get(key(f)) or {}).get("extra_done")]
print(f"{len(todo)} films to fetch trailers/providers")

done = tr = qa = 0
for i, f in enumerate(todo, 1):
    e = data[key(f)]
    d = get(e["tmdb_id"])
    if d:
        e["trailer"] = pick_trailer(d.get("videos", {}).get("results", []))
        e["providers_qa"] = providers(d.get("watch/providers", {}).get("results", {}))
        e["extra_done"] = True
        tr += bool(e["trailer"])
        qa += bool(e["providers_qa"])
    done += 1
    if done % 50 == 0:
        TMDB.write_text(json.dumps(data, indent=1, ensure_ascii=False))
        print(f"  [{i}/{len(todo)}] trailers={tr} qa_providers={qa}", flush=True)
    time.sleep(0.05)

TMDB.write_text(json.dumps(data, indent=1, ensure_ascii=False))
tr_tot = sum(1 for v in data.values() if v.get("trailer"))
qa_tot = sum(1 for v in data.values() if v.get("providers_qa"))
print(f"DONE: {tr_tot} trailers, {qa_tot} with Qatar providers")
