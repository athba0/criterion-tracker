#!/usr/bin/env python3
"""Match films.json against IMDb datasets, add ratings, and rank by weighted score.

Usage: add_ratings.py <title.basics.tsv.gz> <title.ratings.tsv.gz>
Writes data/films_ranked.json and site/films.json.
"""
import csv
import gzip
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASICS, RATINGS = sys.argv[1], sys.argv[2]

films = json.loads((ROOT / "data" / "films.json").read_text())

def norm(title):
    t = unicodedata.normalize("NFKD", title)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower()
    t = re.sub(r"&", "and", t)
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    t = re.sub(r"^(the|a|an|le|la|les|el|il|der|die|das|l) ", "", t)
    return t

wanted = defaultdict(list)  # normalized title -> [film dict]
for f in films:
    wanted[norm(f["title"])].append(f)

TYPES = {"movie", "tvMovie", "short", "tvMiniSeries", "video", "documentary"}

# pass 1: collect IMDb candidates whose title matches any Criterion title
candidates = defaultdict(list)  # film id() -> [(tconst, year_diff)]
tinfo = {}  # tconst -> (runtimeMinutes, genres)
with gzip.open(BASICS, "rt", encoding="utf-8", newline="") as fh:
    reader = csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)
    header = next(reader)
    for row in reader:
        tconst, ttype, primary, original, _adult, start = row[0], row[1], row[2], row[3], row[4], row[5]
        if ttype not in TYPES:
            continue
        keys = {norm(primary)}
        if original != primary:
            keys.add(norm(original))
        hits = [k for k in keys if k in wanted]
        if not hits:
            continue
        try:
            iyear = int(start)
        except ValueError:
            continue
        matched_any = False
        for k in hits:
            for f in wanted[k]:
                if f["year"] is None:
                    continue
                diff = abs(iyear - f["year"])
                if diff <= 1:
                    candidates[id(f)].append((tconst, diff, ttype))
                    matched_any = True
        if matched_any:
            runtime = row[7] if len(row) > 7 and row[7].isdigit() else None
            genres = row[8].split(",") if len(row) > 8 and row[8] not in ("\\N", "") else []
            tinfo[tconst] = (int(runtime) if runtime else None, genres)

ratings = {}
with gzip.open(RATINGS, "rt", encoding="utf-8", newline="") as fh:
    reader = csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)
    next(reader)
    for tconst, avg, votes in reader:
        ratings[tconst] = (float(avg), int(votes))

# pass 2: pick best candidate per film — exact year and 'movie' type preferred,
# then most votes (disambiguates remakes/shorts with the same title+year)
matched = 0
for f in films:
    best = None
    for tconst, diff, ttype in candidates.get(id(f), []):
        if tconst not in ratings:
            continue
        avg, votes = ratings[tconst]
        score = (-diff, ttype == "movie", votes)
        if best is None or score > best[0]:
            best = (score, tconst, avg, votes)
    if best:
        _, tconst, avg, votes = best
        f["imdb_id"], f["imdb_rating"], f["imdb_votes"] = tconst, avg, votes
        f["runtime"], f["genres"] = tinfo.get(tconst, (None, []))
        matched += 1
    else:
        f["imdb_id"] = f["imdb_rating"] = f["imdb_votes"] = f["runtime"] = None
        f["genres"] = []

# Bayesian weighted rating so a 9.1 with 300 votes doesn't outrank an 8.3 with 300k
rated = [f for f in films if f["imdb_rating"] is not None]
C = sum(f["imdb_rating"] for f in rated) / len(rated)
M = 3000
for f in films:
    if f["imdb_rating"] is None:
        f["score"] = None
    else:
        v, r = f["imdb_votes"], f["imdb_rating"]
        f["score"] = round((v / (v + M)) * r + (M / (v + M)) * C, 3)

films.sort(key=lambda f: (f["score"] is None, -(f["score"] or 0), f["spine"] or 10**6))
for i, f in enumerate(films, 1):
    f["rank"] = i

out = json.dumps(films, indent=1, ensure_ascii=False)
(ROOT / "data" / "films_ranked.json").write_text(out)
(ROOT / "site" / "films.json").write_text(out)
print(f"matched {matched}/{len(films)} films (mean rating C={C:.2f})")
print("top 10:")
for f in films[:10]:
    print(f"  {f['rank']:>3}. {f['title']} ({f['year']}) — {f['imdb_rating']} ({f['imdb_votes']:,} votes), score {f['score']}")
