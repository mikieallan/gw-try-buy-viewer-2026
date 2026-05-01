# Try & Buy wine list

Static viewer + optional Python pipeline to parse a Grape Witches Try & Buy `.eml`, enrich from product pages, and attach Vivino data.

**No `package.json`** — static site on Vercel has no npm dependency surface.

## Layout

- `index.html` — viewer (Grape Witches–styled). Expects `/data/try_buy_wines_enriched.json`.
- `data/` — generated JSON/CSV (safe to commit for a public tasting list).
- `scripts/` — parser, local server, tests. See `scripts/README_try_buy_pipeline.md`.

## Local viewer

```bash
python3 scripts/serve_try_buy_viewer.py --port 8765
```

Open http://127.0.0.1:8765/viewer

## Regenerate data

```bash
python3 scripts/parse_try_buy_eml.py --input-eml "/path/to/Try & Buy FAQ.eml"
```

## Vercel

Import this repo (root directory `.`). No build step. Deploy defaults serve `index.html` and `data/`.

## Tests

From this directory:

```bash
python3 -m unittest scripts.tests.test_parse_try_buy_eml scripts.tests.test_vivino_matching
```
