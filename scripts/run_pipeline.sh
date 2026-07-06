#!/usr/bin/env bash
# Finish English summaries, then fetch Arabic (wiki + MT fallback), then rebuild.
set -e
cd "$(dirname "$0")/.."
echo "=== [1/3] English summaries (resume) ==="
python3 scripts/fetch_summaries.py
echo "=== [2/3] Arabic summaries ==="
python3 scripts/fetch_summaries_ar.py
echo "=== [3/3] Rebuild site/films.json ==="
python3 scripts/build_site.py
echo "=== pipeline done ==="
