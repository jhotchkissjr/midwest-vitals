# CLAUDE.md

Instructions for Claude Code working in this repository.

## What this is

A static, auto-updating economic dashboard in the style of econvitals.org, extended with Illinois and Wisconsin data and a bank and credit union layer. The owner works in bank and credit union balance sheet strategy for Illinois and Wisconsin; the audience is economists and financial institution executives. Only public data appears on the site.

## Architecture (keep it this way)

- `config/series.yaml` is the single source of truth for every chart. To add, remove or change a chart, edit the config. Do not hardcode series in Python or JS.
- `pipeline/` (Python) fetches data, applies transforms, writes `site/data/dashboard.json`.
  - `fred.py` FRED API client (needs `FRED_API_KEY`)
  - `fdic.py` FDIC BankFind API, per-institution quarterly data aggregated by state (no key)
  - `ncua.py` NCUA quarterly call report zips, summarized by state; summaries cached in `data_cache/ncua_summary.csv` (commit this file)
  - `transforms.py` yoy, ann_rate, diff, maN, roll12_sum, index_2019, scale
  - `build.py` orchestrator; a failed chart keeps its previous data and is flagged `stale`
  - `validate.py` checks every FRED ID and FDIC field, suggests replacements
  - `ai_notes.py` optional Claude-written section summaries (needs `ANTHROPIC_API_KEY`, skips otherwise)
  - `sample.py` synthetic data for layout work (`--sample`)
- `site/` is plain HTML, CSS and JS with Chart.js vendored in `site/vendor/`. No build step, no framework.
- `.github/workflows/update.yml` runs the pipeline on weekdays, commits data, deploys to GitHub Pages.

## First session checklist

Work through these in order and report results to the owner.

1. `pip install -r requirements.txt` and `python -m pytest -q` (all tests should pass offline).
2. Confirm `.env` has `FRED_API_KEY`. If not, ask the owner to create one at https://fredaccount.stlouisfed.org/apikeys.
3. `python -m pipeline.validate --ncua`. Several IDs in the config are marked `# verify` because they were written from memory:
   - `ILRQGSP`, `WIRQGSP` (quarterly real state GDP)
   - `SMU17000000500000003`, `SMU55000000500000003` (state average hourly earnings)
   - `CUURA207SA0`, `CUURA207SA0L1E` (Chicago CPI, headline and core)
   - `CUUR0200SA0L1E` (Midwest core CPI)
   - FDIC fields `OTHBFHLB`, `BRO`, `NCLNLSR`
   - NCUA account codes in `pipeline/ncua.py` `ACCTS`, especially `ACCT_041B` and `ACCT_661A`
   For any FAIL, use the suggestions the validator prints, or for NCUA run `python -m pipeline.ncua describe YYYY-MM "keyword"`, fix the config or code, and rerun until clean. Also review anything flagged `STALE?` (likely discontinued).
4. `python -m pipeline.build`. The first run downloads about 45 NCUA quarterly zips and pulls roughly 200k FDIC rows; expect several minutes. Read the failure list at the end.
5. Sanity-check real numbers against known values: U.S. unemployment rate and CPI y/y should match the latest BLS releases; Illinois and Wisconsin unemployment should match the latest BLS state release; IL bank count should be in the low-to-mid hundreds and WI in the low hundreds. Flag anything implausible rather than adjusting it silently.
6. `python -m http.server -d site 8000` and check the page in a browser at desktop and phone widths, light and dark mode, with no console errors.
7. Help the owner create the GitHub repo, add secrets (`FRED_API_KEY`, optional `ANTHROPIC_API_KEY`), set Pages source to GitHub Actions, and run the workflow once manually.

## Conventions

- No em dashes anywhere: UI copy, config titles and notes, docs, commit messages, AI prompts. Use commas, colons, parentheses or separate sentences.
- Chart titles say what is measured; `units` says how (for example "% y/y", "%, median bank").
- Colors come from categorical slots 1 to 3 (`--series-N` in `site/styles.css`): U.S. = 1 (navy blue), Illinois = 2 (red), Wisconsin = 3 (teal). The corporate gold is not a series color because it is too close to the red for colorblind readers. Proxies share their state's slot (Chicago = 2, Midwest = 3). Do not add ad hoc colors. If a chart ever needs more than three series, split it or use small multiples.
- One y-axis per chart. If scales differ (for example claims), index to a common base rather than adding a second axis.
- Bank and credit union metrics: prefer medians for ratios and the sub-$10B community cohort for growth, because large Chicago-chartered banks distort Illinois aggregates.
- Keep the site dependency-free beyond vendored Chart.js. If you upgrade Chart.js, replace `site/vendor/chart.umd.min.js` and its license file together.
- Add a pytest for any new transform or metric calculation; tests must run offline.

## Backlog (phase 2, in rough priority order)

1. **Fed speech tracker.** Signature feature of the original site. Pull speeches from the Federal Reserve Board feed (https://www.federalreserve.gov/feeds/speeches.xml) and the Chicago Fed's speeches page (Goolsbee). Send each new speech's text to Claude with a fixed rubric (score from -2 dovish to +2 hawkish on inflation, labor market, and rate path, with a one-sentence justification and a short supporting quote). Store results in `data_cache/speeches.csv` so each speech is scored once. Chart each official's score over time and list the latest five speeches. Keep the rubric and model version in the repo so scores are reproducible.
2. **State JOLTS.** BLS publishes state job openings and quits; find the FRED IDs via `fred.search` and add openings rate and quits rate for IL and WI.
3. **State fiscal.** Census Quarterly Summary of State and Local Tax Revenue (QTAX, Census API `timeseries/eits/qtax`) for IL and WI total tax receipts y/y. Illinois pension funded ratios from the Commission on Government Forecasting and Accountability as an annual chart.
4. **Release calendar.** Use FRED `releases/dates` to show "next release" under each chart.
5. **Credit union borrowings.** Add FHLB and total borrowings share of assets from the NCUA 5300 (find codes with `ncua describe`).
6. **Bank deposit mix.** Uninsured and noninterest-bearing deposit shares by state from FDIC fields, if available in the API.
7. **County unemployment map** for IL and WI from BLS LAUS, as a small choropleth.

## Things not to do

- Do not publish institution-level tables or name individual banks or credit unions; the page is aggregate by design.
- Do not add employer names, logos, taglines or member data. The color palette and font (Verdana) follow the owner's corporate style by the owner's decision; that is the only branding allowed.
- Do not let the AI summaries state causes, forecasts or facts not in the data; keep the system prompt rules in `ai_notes.py`.
