# Try & Buy Wine Pipeline

This script parses a Try & Buy `.eml` file, extracts wines from the `WINE LIST` section, enriches records from Grape Witches product pages, and attempts best-effort Vivino ratings.

## Script

- `scripts/parse_try_buy_eml.py`

## Usage

```bash
python3 scripts/parse_try_buy_eml.py \
  --input-eml "/Users/mikie.allan/Downloads/Try & Buy FAQ.eml"
```

## View Results In Web App

After generating `data/try_buy_wines_enriched.json`, start the local viewer:

```bash
python3 scripts/serve_try_buy_viewer.py --port 8765
```

Then open: `http://127.0.0.1:8765/viewer` (serves the repo root `index.html`).

## Key Flags

- `--dry-run`: run parse + enrichment + Vivino matching and print confidence summary without writing output files.
- `--max-pages`: max Vivino discovery queries per wine.
- `--delay-ms`: base request delay (with jitter) used for all HTTP calls.
- `--output-json`: defaults to `data/try_buy_wines_enriched.json`.
- `--output-csv`: defaults to `data/try_buy_wines_review.csv`.

## Output Semantics

- `gw_winery_display` / `gw_wine_display` / `gw_grape_display` / `gw_region_display`: parsed from Grape Witches `og:title` when it matches `Winery 'Wine' grapes region`.
- `vivino_confidence`: `high`, `medium`, or `low` from fuzzy matching (only when Vivino was resolved via search, not for manual URLs).
- `needs_review`: `true` if confidence is not `high` or no rating candidate was parsed.
- `vivino_match_reason`: scoring explanation, or `Not listed on Vivino (manual list).` for denylisted wines.

## Manual Vivino URLs

Exact Vivino pages are listed in `MANUAL_VIVINO_OVERRIDES_ORDERED` in `scripts/parse_try_buy_eml.py`. When a row matches a needle, only that URL is fetched (no extra search). Wines that are not on Vivino are listed in `NOT_ON_VIVINO_PHRASES`.

## Safeguards

- Requests are throttled with base delay and random jitter.
- Candidate matching is token-scored by producer/cuvee overlap and only accepted when non-trivial.
- Ambiguous or missing matches remain flagged in review output rather than silently filled.

## Important Note

Vivino collection here is unofficial and fragile. HTML structure and anti-bot defenses can change at any time, so this pipeline should be treated as best-effort and not authoritative.
