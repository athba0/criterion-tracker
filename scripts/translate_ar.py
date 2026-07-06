#!/usr/bin/env python3
"""Fill Arabic-summary gaps with machine translation.

TMDB supplies official Arabic overviews for ~famous films; this translates the
English summary (Wikipedia intro or TMDB overview) for every other film via
Google's public translate endpoint. Writes results into data/summaries_ar.json
with src="mt". Films that already have a TMDB Arabic overview are skipped.
Resumable and gently paced.
"""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(name):
    p = ROOT / "data" / name
    return json.loads(p.read_text()) if p.exists() else {}


films = json.loads((ROOT / "data" / "films_ranked.json").read_text())
summaries = load("summaries.json")
tmdb = load("tmdb.json")
OUT = ROOT / "data" / "summaries_ar.json"
ar = load("summaries_ar.json")


def key(f):
    return f"{f['title']}|{f['year']}"


def english(f):
    k = key(f)
    return (summaries.get(k) or {}).get("summary") or (tmdb.get(k) or {}).get("overview_en")


def gtranslate(text):
    q = urllib.parse.urlencode({"client": "gtx", "sl": "en", "tl": "ar", "dt": "t", "q": text})
    url = "https://translate.googleapis.com/translate_a/single?" + q
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.load(r)
            return "".join(seg[0] for seg in data[0] if seg[0]).strip()
        except Exception as e:
            print(f"  MT {e} — wait {8*(attempt+1)}s", flush=True)
            time.sleep(8 * (attempt + 1))
    return None


# films needing MT: have English, no TMDB Arabic, not already MT'd
todo = []
for f in films:
    k = key(f)
    if (tmdb.get(k) or {}).get("overview_ar"):
        continue                       # TMDB already gives Arabic
    if k in ar and ar[k].get("summary_ar"):
        continue                       # already translated
    if english(f):
        todo.append(f)

print(f"{len(todo)} films to machine-translate ({len(ar)} already stored)")
for i, f in enumerate(todo, 1):
    tr = gtranslate(english(f))
    if tr:
        ar[key(f)] = {"summary_ar": tr, "wiki_ar": None, "src": "mt"}
    if i % 20 == 0:
        OUT.write_text(json.dumps(ar, indent=1, ensure_ascii=False))
        print(f"  [{i}/{len(todo)}]", flush=True)
    time.sleep(1.0)

OUT.write_text(json.dumps(ar, indent=1, ensure_ascii=False))
print(f"DONE: {sum(1 for v in ar.values() if v.get('summary_ar'))} MT Arabic summaries stored")
