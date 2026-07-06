#!/usr/bin/env python3
"""Translate the TMDB user reviews to Arabic with DeepL, adding "content_ar".

Breadth-first priority: every film's TOP review (in watch-rank order) is
translated before any second/third reviews, so a limited monthly quota still
covers every reviewed film. Stops cleanly when DeepL's quota is spent (HTTP 456)
and is resumable — reviews with a "content_ar" are skipped.

Reads data/reviews.json (keyed "Title|Year") and rewrites it in place.
Key from secrets.local.json ("deepl_key") or DEEPL_KEY env var; multiple keys in
"deepl_keys" are rotated when one hits its monthly limit.
"""
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REVIEWS = ROOT / "data" / "reviews.json"

sec = json.loads((ROOT / "secrets.local.json").read_text()) if (ROOT / "secrets.local.json").exists() else {}
KEYS = []
if os.environ.get("DEEPL_KEY"):
    KEYS.append(os.environ["DEEPL_KEY"])
KEYS += sec.get("deepl_keys", [])
if sec.get("deepl_key"):
    KEYS.append(sec["deepl_key"])
KEYS = list(dict.fromkeys(k for k in KEYS if k))
if not KEYS:
    raise SystemExit("No DeepL key")
ki = 0


def host(key):
    return "https://api-free.deepl.com" if key.rstrip().endswith(":fx") else "https://api.deepl.com"


films = json.loads((ROOT / "data" / "films_ranked.json").read_text())
rank_of = {f"{f['title']}|{f['year']}": f["rank"] for f in films}
reviews = json.loads(REVIEWS.read_text())


def translate(texts):
    """Translate a batch; rotate keys on quota (456). Returns list or None; sets a
    module flag when all keys are exhausted."""
    global ki
    while ki < len(KEYS):
        body = json.dumps({"text": texts, "source_lang": "EN", "target_lang": "AR"}).encode()
        req = urllib.request.Request(host(KEYS[ki]) + "/v2/translate", data=body, method="POST",
            headers={"Authorization": "DeepL-Auth-Key " + KEYS[ki], "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return [t["text"] for t in json.load(r)["translations"]]
        except urllib.error.HTTPError as e:
            if e.code == 456:
                print(f"  key #{ki + 1} monthly quota spent — rotating", flush=True)
                ki += 1
                continue
            if e.code == 429:
                time.sleep(8)
            else:
                print(f"  HTTP {e.code}: {e.read().decode(errors='ignore')[:120]}", flush=True)
                time.sleep(4)
        except Exception as e:
            print(f"  {e}", flush=True)
            time.sleep(4)
    return "EXHAUSTED"


# priority queue: every film's TOP review first (by rank), then 2nd, then 3rd
maxlen = max((len(v) for v in reviews.values()), default=0)
queue = []
for idx in range(maxlen):
    tier = [(k, idx, reviews[k][idx]["content"]) for k in reviews
            if idx < len(reviews[k]) and not reviews[k][idx].get("content_ar")]
    tier.sort(key=lambda x: rank_of.get(x[0], 10**6))
    queue += tier

print(f"{len(queue)} reviews to translate (breadth-first by rank)")

BATCH = 20
done = 0
for i in range(0, len(queue), BATCH):
    chunk = queue[i : i + BATCH]
    res = translate([c[2] for c in chunk])
    if res == "EXHAUSTED":
        print("all DeepL quota spent — stopping (resume next cycle / add a key)")
        break
    if not res:
        continue
    for (k, idx, _), tr in zip(chunk, res):
        reviews[k][idx]["content_ar"] = tr.strip()
    done += len(chunk)
    REVIEWS.write_text(json.dumps(reviews, ensure_ascii=False, separators=(",", ":")))
    if (i // BATCH) % 5 == 0:
        print(f"  {done}/{len(queue)} translated", flush=True)
    time.sleep(0.4)

REVIEWS.write_text(json.dumps(reviews, ensure_ascii=False, separators=(",", ":")))
tot = sum(1 for v in reviews.values() for r in v)
tr = sum(1 for v in reviews.values() for r in v if r.get("content_ar"))
covered = sum(1 for v in reviews.values() if any(r.get("content_ar") for r in v))
print(f"DONE: {tr}/{tot} reviews translated, {covered}/{len(reviews)} films have an Arabic review")
