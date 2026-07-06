#!/usr/bin/env python3
"""Fetch festival/awards + colour info from Wikidata, matched by IMDb id.

Batched SPARQL over query.wikidata.org (POST — the GET endpoint is being
rate-limited during a WDQS outage). Writes data/wikidata.json keyed by
"Title|Year": {"awards": [tags], "award_labels": [...], "color": "bw"|"color"}.
Resumable: films already present are skipped.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "wikidata.json"
SPARQL = "https://query.wikidata.org/sparql"
UA = "criterion-tracker/1.0 (personal film tracker; github athba0)"

films = json.loads((ROOT / "data" / "films_ranked.json").read_text())
data = json.loads(OUT.read_text()) if OUT.exists() else {}


def key(f):
    return f"{f['title']}|{f['year']}"


imdb_to_key = {f["imdb_id"]: key(f) for f in films if f.get("imdb_id")}

# award label (lowercased substring) -> display tag
AWARD_MAP = [
    ("palme d", "Palme d'Or"),
    ("academy award", "Oscar"),
    ("golden lion", "Golden Lion (Venice)"),
    ("golden bear", "Golden Bear (Berlin)"),
    ("bafta", "BAFTA"),
    ("golden globe", "Golden Globe"),
    ("césar", "César"), ("cesar award", "César"),
    ("grand prix", "Cannes Grand Prix"),
]


def categorize(labels):
    tags = set()
    for l in labels:
        ll = l.lower()
        for needle, tag in AWARD_MAP:
            if needle in ll:
                tags.add(tag)
    return sorted(tags)


def query(imdb_ids):
    values = " ".join('"%s"' % i for i in imdb_ids)
    q = ("SELECT ?imdb ?awardLabel ?colorLabel WHERE { VALUES ?imdb { " + values + " } "
         "?item wdt:P345 ?imdb. "
         'OPTIONAL { ?item wdt:P166 ?a. ?a rdfs:label ?awardLabel. FILTER(LANG(?awardLabel)="en") } '
         'OPTIONAL { ?item wdt:P462 ?c. ?c rdfs:label ?colorLabel. FILTER(LANG(?colorLabel)="en") } }')
    body = urllib.parse.urlencode({"query": q, "format": "json"}).encode()
    for attempt in range(6):
        try:
            req = urllib.request.Request(SPARQL, data=body,
                                         headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            wait = 65 if e.code == 429 else 8 * (attempt + 1)
            print(f"  HTTP {e.code} — wait {wait}s", flush=True)
            time.sleep(wait)
        except Exception as e:
            print(f"  {e} — wait 8s", flush=True)
            time.sleep(8)
    return None


pending = [i for i in imdb_to_key if imdb_to_key[i] not in data]
print(f"{len(pending)} films to look up on Wikidata ({len(data)} cached)")

BATCH = 100
for start in range(0, len(pending), BATCH):
    chunk = pending[start : start + BATCH]
    d = query(chunk)
    if not d:
        continue
    aw = defaultdict(set)
    col = defaultdict(set)
    for b in d["results"]["bindings"]:
        im = b["imdb"]["value"]
        if "awardLabel" in b:
            aw[im].add(b["awardLabel"]["value"])
        if "colorLabel" in b:
            col[im].add(b["colorLabel"]["value"])
    for im in chunk:
        k = imdb_to_key[im]
        labels = sorted(aw.get(im, []))
        colours = {c.lower() for c in col.get(im, [])}
        color = "color" if any("colour" in c or "color" in c for c in colours) \
            else ("bw" if any("black" in c for c in colours) else None)
        data[k] = {"awards": categorize(labels), "award_labels": labels[:6], "color": color}
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    print(f"  [{min(start + BATCH, len(pending))}/{len(pending)}] cached", flush=True)
    time.sleep(6)

won = sum(1 for v in data.values() if v.get("awards"))
bw = sum(1 for v in data.values() if v.get("color") == "bw")
print(f"DONE: {len(data)} films, {won} with a mapped award, {bw} black-and-white")
