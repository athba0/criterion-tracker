#!/usr/bin/env python3
"""Translate each film's English plot to Arabic with the DeepL API (Free tier).

Only films WITHOUT a native TMDB Arabic overview are translated; TMDB's official
Arabic is preferred in build_site.py. Translates the full English plot (TMDB
overview, else Wikipedia intro). Batched (DeepL accepts many texts per request),
resumable, and reports character usage against the monthly free quota.

Key from secrets.local.json ("deepl_key") or the DEEPL_KEY env var. Free keys end
in ":fx" and use the api-free host (auto-detected). Writes
data/summaries_ar_deepl.json: {"Title|Year": {"summary_ar": str, "src": "deepl"}}
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "summaries_ar_deepl.json"


def load(name):
    p = ROOT / "data" / name
    return json.loads(p.read_text()) if p.exists() else {}


sec = json.loads((ROOT / "secrets.local.json").read_text()) if (ROOT / "secrets.local.json").exists() else {}
KEY = os.environ.get("DEEPL_KEY") or sec.get("deepl_key")
if not KEY:
    raise SystemExit("No DeepL key (set DEEPL_KEY or secrets.local.json deepl_key)")
HOST = "https://api-free.deepl.com" if KEY.rstrip().endswith(":fx") else "https://api.deepl.com"
HDR = {"Authorization": "DeepL-Auth-Key " + KEY, "Content-Type": "application/json"}

films = json.loads((ROOT / "data" / "films_ranked.json").read_text())
summaries = load("summaries.json")
tmdb = load("tmdb.json")
out = load("summaries_ar_deepl.json")


def key(f):
    return f"{f['title']}|{f['year']}"


def english(f):
    k = key(f)
    return (tmdb.get(k) or {}).get("overview_en") or (summaries.get(k) or {}).get("summary")


def post(path, payload):
    data = json.dumps(payload).encode()
    for attempt in range(6):
        try:
            req = urllib.request.Request(HOST + path, data=data, headers=HDR, method="POST")
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 456:
                raise SystemExit("DeepL quota exhausted for this month — stopping (resume next cycle)")
            if e.code == 429:
                time.sleep(5 * (attempt + 1))
            else:
                body = e.read().decode(errors="ignore")[:200]
                print(f"  HTTP {e.code}: {body}", flush=True)
                time.sleep(3 * (attempt + 1))
        except Exception as e:
            print(f"  {e}", flush=True)
            time.sleep(3 * (attempt + 1))
    return None


def usage():
    try:
        req = urllib.request.Request(HOST + "/v2/usage", headers={"Authorization": HDR["Authorization"]})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except Exception:
        return {}


# films needing DeepL: have English, no native TMDB Arabic, not already translated
todo = []
for f in films:
    k = key(f)
    if (tmdb.get(k) or {}).get("overview_ar"):
        continue
    if (out.get(k) or {}).get("summary_ar"):
        continue
    if english(f):
        todo.append(f)

u0 = usage()
print(f"{len(todo)} plots to translate. DeepL usage: "
      f"{u0.get('character_count', '?')}/{u0.get('character_limit', '?')} chars")

BATCH = 25
for i in range(0, len(todo), BATCH):
    chunk = todo[i : i + BATCH]
    texts = [english(f) for f in chunk]
    res = post("/v2/translate", {"text": texts, "source_lang": "EN", "target_lang": "AR"})
    if not res or "translations" not in res:
        print("  batch failed, skipping", flush=True)
        continue
    for f, tr in zip(chunk, res["translations"]):
        txt = (tr.get("text") or "").strip()
        if txt:
            out[key(f)] = {"summary_ar": txt, "src": "deepl"}
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"  [{min(i + BATCH, len(todo))}/{len(todo)}] translated", flush=True)
    time.sleep(0.5)

u1 = usage()
print(f"DONE: {len(out)} DeepL Arabic plots. Usage now: "
      f"{u1.get('character_count', '?')}/{u1.get('character_limit', '?')} chars")
