# Criterion Tracker

A static, self-contained tracker for every Criterion Collection release (1,847 films),
ranked by "what to watch first" using IMDb ratings weighted by vote count (Bayesian
average), so acclaimed essentials rank above obscure high-variance titles.

**Live use:** open the site, tick films as you watch them, rate (1–5 ★) and write a
review per film. Everything is saved in your browser's localStorage.

## Features

- Full spine list scraped from criterion.com (incl. box-set contents without spines)
- Ranked by IMDb weighted score; search + watched/decade filters
- Per-film: watched toggle, watch date, star rating, review editor
- Links to each film's Letterboxd search, Criterion page, and IMDb page
- **Export Letterboxd CSV** — outputs `Title, Year, Rating, WatchedDate, Review` in
  [Letterboxd's import format](https://letterboxd.com/about/importing-data/); upload at
  letterboxd.com/import to publish all your ratings & reviews in one go
- **Backup / Restore** — progress is localStorage-only, so export the JSON backup
  occasionally (or commit it to this repo) to survive browser resets

## Deploy on GitHub Pages

```sh
gh repo create criterion-tracker --public --source . --push
gh api repos/{owner}/criterion-tracker/pages -X POST \
  -f 'source[branch]=main' -f 'source[path]=/'
```

Then visit `https://<user>.github.io/criterion-tracker/site/`.
(Or in the repo settings: Pages → deploy from branch `main`, root folder.)

## Refreshing the data

```sh
# 1. Get the film list (criterion.com is behind Cloudflare; use a Wayback snapshot)
curl -sL -o /tmp/criterion_list.html \
  "http://web.archive.org/web/2/https://www.criterion.com/shop/browse/list?sort=spine_number"
python3 scripts/parse_criterion.py /tmp/criterion_list.html

# 2. Re-rank with fresh IMDb data (free public datasets)
curl -sO https://datasets.imdbws.com/title.basics.tsv.gz
curl -sO https://datasets.imdbws.com/title.ratings.tsv.gz
python3 scripts/add_ratings.py title.basics.tsv.gz title.ratings.tsv.gz
```

`add_ratings.py` matches ~88% of films (unmatched ones — mostly shorts and box-set
oddities — sort to the bottom as "unrated"). Ranking formula:
`WR = v/(v+m)·R + m/(v+m)·C` with `m = 3000` votes and `C` = collection mean (~7.26).

## Local preview

```sh
python3 -m http.server 8763 --directory site
```
