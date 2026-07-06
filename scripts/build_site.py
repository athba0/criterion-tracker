#!/usr/bin/env python3
"""Merge films_ranked.json + summaries.json and precompute per-film
"if you liked this" recommendations -> site/films.json."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
films = json.loads((ROOT / "data" / "films_ranked.json").read_text())


def load(name):
    p = ROOT / "data" / name
    return json.loads(p.read_text()) if p.exists() else {}


summaries = load("summaries.json")     # EN + AR from Wikipedia
ar = load("summaries_ar.json")         # AR from ar.wikipedia / machine translation
tmdb = load("tmdb.json")               # EN + AR overviews from TMDB

# Source priority — English: Wikipedia intro (encyclopedic) then TMDB overview.
# Arabic: TMDB official overview, then ar.wikipedia intro, then machine translation.
for f in films:
    k = f"{f['title']}|{f['year']}"
    s = summaries.get(k) or {}
    a = ar.get(k) or {}
    t = tmdb.get(k) or {}

    f["summary"] = s.get("summary") or t.get("overview_en")
    f["wiki"] = s.get("wiki")
    f["tmdb_id"] = t.get("tmdb_id")

    if t.get("overview_ar"):
        f["summary_ar"], f["ar_src"] = t["overview_ar"], "tmdb"
    elif a.get("summary_ar"):
        f["summary_ar"], f["ar_src"] = a["summary_ar"], a.get("src")
    else:
        f["summary_ar"], f["ar_src"] = None, None
    f["wiki_ar"] = a.get("wiki_ar")

# --- similarity: same director >> genre overlap > country > era > quality ---
def sim(a, b):
    score = 0.0
    if a["director"] and a["director"] == b["director"]:
        score += 4.0
    ga, gb = set(a.get("genres") or []), set(b.get("genres") or [])
    if ga and gb:
        score += 3.0 * len(ga & gb) / len(ga | gb)
    if a["country"] and a["country"] == b["country"]:
        score += 1.0
    if a["year"] and b["year"]:
        dy = abs(a["year"] - b["year"])
        score += max(0.0, 1.0 - dy / 25.0)
    return score

# bucket by director / genre / country so we don't do a full 1847^2 scan
from collections import defaultdict

buckets = defaultdict(set)
for i, f in enumerate(films):
    if f["director"]:
        buckets["d:" + f["director"]].add(i)
    for g in f.get("genres") or []:
        buckets["g:" + g].add(i)
    if f["country"]:
        buckets["c:" + f["country"]].add(i)

for i, f in enumerate(films):
    cand = set()
    if f["director"]:
        cand |= buckets["d:" + f["director"]]
    for g in f.get("genres") or []:
        cand |= buckets["g:" + g]
    if f["country"]:
        cand |= buckets["c:" + f["country"]]
    cand.discard(i)
    scored = []
    for j in cand:
        g = films[j]
        s = sim(f, g)
        if s <= 1.0:
            continue
        # nudge acclaimed films up so recs are watch-worthy
        s += (g["score"] or 6.5) / 10.0
        scored.append((s, j))
    scored.sort(reverse=True)
    # cap same-director picks at 3 so recs aren't a single filmography
    picks, per_dir = [], defaultdict(int)
    for s, j in scored:
        d = films[j]["director"]
        if d and d == f["director"] and per_dir[d] >= 3:
            continue
        per_dir[films[j]["director"]] += 1
        picks.append(j)
        if len(picks) == 6:
            break
    f["similar"] = [films[j]["rank"] for j in picks]

out = json.dumps(films, ensure_ascii=False, separators=(",", ":"))
(ROOT / "site" / "films.json").write_text(out)
with_sum = sum(1 for f in films if f["summary"])
with_ar = sum(1 for f in films if f["summary_ar"])
print(f"site/films.json: {len(films)} films, {with_sum} EN summaries, "
      f"{with_ar} AR summaries, "
      f"{sum(1 for f in films if f['similar'])} with recommendations, "
      f"{len(out) // 1024} KB")
print("recs for Seven Samurai:",
      [films[r - 1]["title"] for r in next(f for f in films if f["title"] == "Seven Samurai")["similar"]])
