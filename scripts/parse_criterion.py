#!/usr/bin/env python3
"""Parse the Criterion shop list HTML (Wayback snapshot) into data/films.json."""
import json
import re
import sys
from html import unescape
from pathlib import Path

SRC = sys.argv[1] if len(sys.argv) > 1 else "criterion_list.html"
OUT = Path(__file__).resolve().parent.parent / "data" / "films.json"

html = open(SRC, encoding="utf-8").read()

rows = re.findall(
    r'<tr class="gridFilm"[^>]*data-href="([^"]*)"[^>]*>(.*?)</tr>', html, re.S
)

def cell(row_html, cls):
    m = re.search(r'<td class="g-%s">(.*?)</td>' % cls, row_html, re.S)
    if not m:
        return ""
    text = re.sub(r"<[^>]+>", " ", m.group(1))
    return unescape(re.sub(r"\s+", " ", text)).strip(" ,")

films = []
for href, body in rows:
    spine = cell(body, "spine")
    year = cell(body, "year")
    # strip wayback prefix from the film URL
    url = re.sub(r"^https?://web\.archive\.org/web/\d+(?:im_)?/", "", href)
    # box-art image: strip wayback prefix and the size suffix; the S3 bucket
    # serves _thumbnail/_small/_medium/_large variants of the same base name
    img = None
    m = re.search(r'<img src="([^"]+)"', body)
    if m:
        img = re.sub(r"^https?://web\.archive\.org/web/\d+(?:im_)?/", "", m.group(1))
        img = re.sub(r"_(thumbnail|small|medium|large)\.jpg$", "", img)
    films.append(
        {
            "spine": int(spine) if spine.isdigit() else None,
            "title": cell(body, "title"),
            "director": cell(body, "director"),
            "country": cell(body, "country").replace(" ,", ","),
            "year": int(year) if year.isdigit() else None,
            "url": url,
            "img": img,
        }
    )

films = [f for f in films if f["title"]]
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(films, indent=1, ensure_ascii=False))
print(f"wrote {len(films)} films -> {OUT}")
print("sample:", json.dumps(films[0], ensure_ascii=False))
print("no-spine entries:", sum(1 for f in films if f["spine"] is None))
