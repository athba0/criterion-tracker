#!/usr/bin/env python3
"""Add Arabic summaries to each film, two-tier:

 1. Arabic Wikipedia intro — follow EN->AR interlanguage links from the English
    article we already matched, and use that article's own intro (authentic prose).
 2. Machine translation — for films with no Arabic article, translate the English
    summary via Google's public translate endpoint.

Reads data/summaries.json (English summaries + wiki URLs), writes
data/summaries_ar.json keyed by "Title|Year":
    {"summary_ar": str|None, "wiki_ar": url|None, "src": "wiki"|"mt"|None}
Resumable: entries already present with a summary_ar are skipped.
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENG = ROOT / "data" / "summaries.json"
OUT = ROOT / "data" / "summaries_ar.json"
UA = {"User-Agent": "criterion-tracker/1.0 (personal film tracker; github athba0)"}
EN_API = "https://en.wikipedia.org/w/api.php"
AR_API = "https://ar.wikipedia.org/w/api.php"

films = json.loads((ROOT / "data" / "films_ranked.json").read_text())
eng = json.loads(ENG.read_text())
ar = json.loads(OUT.read_text()) if OUT.exists() else {}
ar = {k: v for k, v in ar.items() if v.get("summary_ar")}  # retry misses


def key(f):
    return f"{f['title']}|{f['year']}"


def title_from_url(url):
    if not url:
        return None
    seg = urllib.parse.unquote(url.rsplit("/wiki/", 1)[-1])
    return seg.replace("_", " ")


def http_json(url):
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            ra = e.headers.get("Retry-After") if e.headers else None
            wait = int(ra) if ra and ra.isdigit() else 12 * 2 ** attempt
            print(f"  {e} — wait {min(wait,240)}s", flush=True)
            time.sleep(min(wait, 240))
        except Exception as e:
            print(f"  {e} — wait 12s", flush=True)
            time.sleep(12)
    return None


def shorten(text):
    text = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?؟।]) ", text)
    short = " ".join(parts[:2])
    if len(short) > 420:
        short = short[:417].rsplit(" ", 1)[0] + "…"
    return short


def batched(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def gtranslate(text):
    """Google's public translate endpoint. Returns Arabic text or None."""
    q = urllib.parse.urlencode(
        {"client": "gtx", "sl": "en", "tl": "ar", "dt": "t", "q": text}
    )
    url = "https://translate.googleapis.com/translate_a/single?" + q
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.load(r)
            return "".join(seg[0] for seg in data[0] if seg[0])
        except Exception as e:
            print(f"  MT {e} — wait {8*(attempt+1)}s", flush=True)
            time.sleep(8 * (attempt + 1))
    return None


# --- films that have an English article and still need Arabic ---
todo = [f for f in films if key(f) not in ar and (eng.get(key(f)) or {}).get("wiki")]
print(f"{len(todo)} films need Arabic ({len(ar)} already done)")

# STEP 1: EN->AR interlanguage links (50 titles/request)
en_title = {key(f): title_from_url(eng[key(f)]["wiki"]) for f in todo}
ar_title = {}  # film key -> Arabic article title
for chunk in batched(todo, 50):
    titles = [en_title[key(f)] for f in chunk]
    params = {
        "action": "query", "format": "json", "redirects": 1,
        "prop": "langlinks", "lllang": "ar", "lllimit": "max",
        "titles": "|".join(titles),
    }
    d = http_json(EN_API + "?" + urllib.parse.urlencode(params))
    if not d:
        continue
    q = d.get("query", {})
    norm = {n["to"]: n["from"] for n in q.get("normalized", [])}
    redir = {n["to"]: n["from"] for n in q.get("redirects", [])}
    title_to_ar = {}
    for p in q.get("pages", {}).values():
        ll = p.get("langlinks")
        if ll:
            title_to_ar[p["title"]] = ll[0]["*"]
    for f in chunk:
        t = en_title[key(f)]
        # resolve our queried title through redirect/normalize to the page title
        for page_title, artitle in title_to_ar.items():
            cand = page_title
            if cand in redir:
                cand = redir[cand]
            if cand in norm:
                cand = norm[cand]
            if cand == t or page_title == t:
                ar_title[key(f)] = artitle
                break
    time.sleep(3)

print(f"  {len(ar_title)} have Arabic Wikipedia articles")

# STEP 2: fetch Arabic intros for those (20 titles/request)
have_ar = [f for f in todo if key(f) in ar_title]
for chunk in batched(have_ar, 20):
    titles = [ar_title[key(f)] for f in chunk]
    params = {
        "action": "query", "format": "json", "redirects": 1,
        "prop": "extracts|info", "exintro": 1, "explaintext": 1,
        "exlimit": "max", "inprop": "url", "titles": "|".join(titles),
    }
    d = http_json(AR_API + "?" + urllib.parse.urlencode(params))
    if not d:
        continue
    q = d.get("query", {})
    norm = {n["to"]: n["from"] for n in q.get("normalized", [])}
    redir = {n["to"]: n["from"] for n in q.get("redirects", [])}
    by_title = {}
    for p in q.get("pages", {}).values():
        cand = p.get("title")
        if cand in redir:
            cand = redir[cand]
        if cand in norm:
            cand = norm[cand]
        by_title[cand] = p
    for f in chunk:
        p = by_title.get(ar_title[key(f)])
        ex = (p or {}).get("extract", "").strip()
        if ex and len(ex) > 40:
            ar[key(f)] = {"summary_ar": shorten(ex), "wiki_ar": p.get("fullurl"), "src": "wiki"}
    OUT.write_text(json.dumps(ar, indent=1, ensure_ascii=False))
    print(f"  wiki: {sum(1 for v in ar.values() if v['src']=='wiki')} done", flush=True)
    time.sleep(3)

# STEP 3: machine-translate the rest (no Arabic article, but has English summary)
need_mt = [
    f for f in todo
    if key(f) not in ar and (eng.get(key(f)) or {}).get("summary")
]
print(f"machine-translating {len(need_mt)} films")
for i, f in enumerate(need_mt, 1):
    tr = gtranslate(eng[key(f)]["summary"])
    if tr:
        ar[key(f)] = {"summary_ar": tr.strip(), "wiki_ar": None, "src": "mt"}
    if i % 20 == 0:
        OUT.write_text(json.dumps(ar, indent=1, ensure_ascii=False))
        print(f"  mt: {i}/{len(need_mt)}", flush=True)
    time.sleep(1.2)

OUT.write_text(json.dumps(ar, indent=1, ensure_ascii=False))
w = sum(1 for v in ar.values() if v["src"] == "wiki")
m = sum(1 for v in ar.values() if v["src"] == "mt")
print(f"DONE: {len(ar)} Arabic summaries ({w} from ar.wikipedia, {m} machine-translated)")
