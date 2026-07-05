#!/usr/bin/env python3
"""Fetch a short summary for each film from Wikipedia's batch query API.

Three rounds of candidate titles — "Title (YEAR film)", "Title (film)", "Title"
— 20 titles per request, keeping pages that look like the right film article.
Resumable: films already in data/summaries.json with a summary are skipped;
null entries are retried.
"""
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "summaries.json"
UA = {"User-Agent": "criterion-tracker/1.0 (personal film tracker; contact via github)"}
API = "https://en.wikipedia.org/w/api.php"

films = json.loads((ROOT / "data" / "films_ranked.json").read_text())
summaries = json.loads(OUT.read_text()) if OUT.exists() else {}
# retry anything that previously failed
summaries = {k: v for k, v in summaries.items() if v.get("summary")}

def key(f):
    return f"{f['title']}|{f['year']}"

def api_query(titles):
    """Batch-fetch intro extracts for up to 20 titles. Returns {queried_title: page}."""
    params = {
        "action": "query", "format": "json", "redirects": 1,
        "prop": "extracts|info", "exintro": 1, "explaintext": 1,
        "exlimit": "max", "inprop": "url",
        "titles": "|".join(titles),
    }
    url = API + "?" + urllib.parse.urlencode(params)
    for attempt in range(8):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            break
        except urllib.error.HTTPError as e:
            retry_after = e.headers.get("Retry-After") if e.headers else None
            wait = int(retry_after) if retry_after and retry_after.isdigit() else 15 * 2 ** attempt
            print(f"  retry in {wait}s ({e})", flush=True)
            time.sleep(min(wait, 300))
        except Exception as e:
            print(f"  retry in 15s ({e})", flush=True)
            time.sleep(15)
    else:
        return {}
    q = data.get("query", {})
    # map normalized/redirected names back to what we asked for
    back = {}
    for n in q.get("normalized", []) + q.get("redirects", []):
        back[n["to"]] = back.get(n["from"], n["from"])
        # chase one level: from may itself be a normalization target
    resolved = {}
    for page in q.get("pages", {}).values():
        t = page.get("title")
        orig = t
        seen = set()
        while orig in back and orig not in seen:
            seen.add(orig)
            orig = back[orig]
        resolved[orig] = page
    return resolved

FILMY = re.compile(r"\b(film|movie|documentary|mini-?series|anthology|short)\b", re.I)

def accept(page, f):
    if not page or "missing" in page or "invalid" in page:
        return None
    text = page.get("extract") or ""
    if not text or not FILMY.search(text[:500]):
        return None
    years = [int(y) for y in re.findall(r"\b(18\d\d|19\d\d|20\d\d)\b", text[:300])]
    if years and f["year"] and min(abs(y - f["year"]) for y in years) > 2:
        return None
    extract = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?]) (?=[A-Z0-9\"'])", extract)
    short = " ".join(parts[:2])
    if len(short) > 400:
        short = short[:397].rsplit(" ", 1)[0] + "…"
    return {"summary": short, "wiki": page.get("fullurl")}

def batched(seq, n=20):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]

pending = [f for f in films if key(f) not in summaries]
print(f"{len(pending)} films to fetch, {len(summaries)} already done")

for rnd, cand_fn in enumerate([
    lambda f: f"{f['title']} ({f['year']} film)",
    lambda f: f"{f['title']} (film)",
    lambda f: f["title"],
]):
    if not pending:
        break
    print(f"--- round {rnd + 1}: {len(pending)} films", flush=True)
    still = []
    for chunk in batched(pending):
        asked = {cand_fn(f): f for f in chunk}
        pages = api_query(list(asked))
        for cand, f in asked.items():
            got = accept(pages.get(cand), f)
            if got:
                summaries[key(f)] = got
            else:
                still.append(f)
        OUT.write_text(json.dumps(summaries, indent=1, ensure_ascii=False))
        print(f"  {len(summaries)} done", flush=True)
        time.sleep(4)
    pending = still

for f in pending:
    summaries[key(f)] = {"summary": None, "wiki": None}
OUT.write_text(json.dumps(summaries, indent=1, ensure_ascii=False))
got = sum(1 for v in summaries.values() if v["summary"])
print(f"DONE: {got}/{len(films)} films have summaries, {len(pending)} unmatched")
