# India Capitals Weather Pipeline

An automated daily ETL pipeline for the **capital city of every Indian state and
union territory**: 34 cities covering all 28 states and 8 UTs. It pulls weather
data from the public [Open-Meteo API](https://open-meteo.com), loads it into SQLite, and rebuilds a
set of SQL report tables. It then publishes the results in two ways: an
interactive HTML dashboard, and CSV exports that Power BI reads (see
[powerbi/POWERBI_GUIDE.md](powerbi/POWERBI_GUIDE.md)).

Everything uses the Python standard library: no `pip install` and no API key.

```
 Open-Meteo API ──► extract.py ──► transform.py ──► load.py ──► SQLite
  (archive +        retries,       reshape,         idempotent   │
   forecast)        backoff        validate,        upserts,     ▼
                                   reject bad rows  run audit   sql/reports/*.sql
                                                                 │  (CREATE TABLE AS)
                                                    ┌────────────┴────────────┐
                                                    ▼                         ▼
                                          dashboard/index.html     powerbi/data/*.csv ──► Power BI
```

## Dashboard

The Power BI report **The Weather Report** has 6 pages. Every page can be
filtered by region, and pages 3–5 let you compare up to 4 cities.

### 1. National Overview
All 34 capitals on a map of India, with the hottest and wettest capitals of the last 30 days.

![National Overview](images/1_national_overview.png)

### 2. Regional Overview
Monthly rainfall heatmap by region, showing when the monsoon arrives in each part of India.

![Regional Overview](images/2_regional_overview.png)

### 3. City Temperature
7-day rolling temperature for selected cities, the biggest day/night temperature gaps, and month-over-month change.

![City Temperature](images/3_city_temperature.png)

### 4. Rainfall & Dry Spells
Monthly rainfall, rainy days per month for every capital, and the longest run of dry days.

![Rainfall and Dry Spells](images/4_rainfall_dry_spells.png)

### 5. 7 Day Forecast
Heavy-rain risk for all capitals over the next 7 days, with daily highs, lows and conditions.

![7 Day Forecast](images/5_forecast.png)

### 6. Pipeline Health and Data Quality
Status of every pipeline run and data-quality checks for each city.

![Pipeline Health and Data Quality](images/6_pipeline_health.png)

## Quick start

Requires Python 3.9 or later. There is nothing to install.

```bash
python run_pipeline.py            # first run backfills 365 days (~2 min), then refreshes daily
python -m unittest -v             # offline tests (no network)
```

The first run creates these files:

- `data/weather.db` is the SQLite database.
- `powerbi/data/*.csv` are the files Power BI reads.
- `dashboard/index.html` is the HTML dashboard. Open it in a browser.
- `logs/pipeline.log` is the run log.

**In VS Code:** open the folder, then use **Run and Debug > "Run pipeline (daily)"**.
To run the tests, open the **Testing** panel (beaker icon). Both are set up in `.vscode/`.

**In Power BI:** follow [powerbi/POWERBI_GUIDE.md](powerbi/POWERBI_GUIDE.md).
The report is branded **The Weather Report**: 6 pages at 1920 × 1080 on a
blue-panel background, with navy text. The page backgrounds are SVG files in
`powerbi/backgrounds/`. To reuse one: select a page, open **Format pane >
Canvas background > Image**, choose the SVG, and set **Image fit** to **Fill**
and **Transparency** to **0%**.

Options:

| Command | What it does |
|---|---|
| `python run_pipeline.py` | Incremental daily run |
| `python run_pipeline.py --backfill-days 730` | Load a longer history on the first run |
| `python run_pipeline.py --reports-only` | Rebuild reports, the dashboard and the CSVs without calling the API |

## Coverage

Each city in `config.json` has these columns, which also appear in every city-level CSV:

| Column | Example |
|---|---|
| `name` (`city` in the CSVs) | Thiruvananthapuram |
| `state_ut` | Kerala |
| `state_type` | State / Union Territory |
| `region` | North · Central · East · Northeast · West · South |
| `capital_of` | `Chandigarh; Punjab; Haryana` (Chandigarh serves three) |

Regions: North 8 · Central 2 · East 5 · Northeast 8 · West 4 · South 7.

**To add or remove cities**, edit `config.json`. Every city needs `name`,
`state_ut`, `region`, `latitude` and `longitude`. New cities are backfilled
automatically on the next run. Removed cities keep their history but are hidden
from the reports (`dim_city.is_active = 0`). There is no need to delete the
database.

## Engineering highlights

- **Incremental loading.** Each run checks the last observed date for every city.
  It uses the archive endpoint for big gaps (for example, the first run) and the
  forecast endpoint's `past_days` for recent days. A normal daily run makes 1 API
  call per city. If the job was missed for a week, the next run catches up on its own.
- **Idempotent upserts.** The primary key is `(city_id, obs_date)` and rows are
  written with `ON CONFLICT DO UPDATE`, so re-running never creates duplicates.
  Forecast rows (`is_forecast = 1`) are overwritten by actuals once the day has passed.
- **Validation layer.** Rows are rejected if all temperatures are null, if
  min > max, if a value is outside physical limits, or if rain is negative.
  Rejected rows are logged and counted.
- **Rate limiting.** Open-Meteo's free tier allows 600 weighted calls per minute,
  and a 1-year history request weighs about 16 calls. Requests are spaced out
  (`request_delay_seconds`). If the API still returns HTTP 429, the pipeline waits
  for the `Retry-After` time and retries. Network errors and 5xx responses are
  retried with exponential backoff.
- **Partial-failure tolerance.** If one city fails to download, the other 33 are
  still loaded. The run is marked `partial`, with the failed cities named in
  `pipeline_runs.error`, and the next run fills in the gap automatically.
- **Schema migrations.** A database created by an older version gets the new
  `dim_city` columns added on connect (`ALTER TABLE`), so existing data is kept.
- **Config validation.** Duplicate city names, or missing required fields in
  `config.json`, stop the run before any API call is made.
- **Run audit.** Every run writes to `pipeline_runs` with its status, row
  counts, API calls and any error. A failed run is recorded and returns a
  non-zero exit code, so the scheduler can alert on it.
- **Power BI export.** Every run writes the model tables and report tables to
  `powerbi/data/*.csv`. Files are written to a temp file and then swapped in, so
  Power BI never reads a half-written file.
- **SQL-driven reports.** Each file in `sql/reports/` rebuilds one report table,
  and you add a report by dropping in a new `.sql` file.

## SQL reports

| Table | Technique |
|---|---|
| `report_city_summary_30d` | Aggregates, `ROW_NUMBER()` for each city's hottest day, `RANK()` for national hot/wet rankings |
| `report_daily_trend` | 7-day rolling average with `AVG() OVER (ROWS BETWEEN 6 PRECEDING ...)` |
| `report_monthly` | Monthly roll-up with month-over-month change using `LAG()` |
| `report_region_monthly` | Two-level aggregation (city, then region), so regions with more cities don't dominate |
| `report_dry_streaks` | Longest dry spell using the **gaps-and-islands** pattern |
| `report_forecast` | Upcoming forecast rows |
| `report_data_quality` | Coverage, missing days, nulls, freshness, and a PASS/WARN/FAIL status |

## Scheduling

**Windows (Task Scheduler):**
```powershell
powershell -ExecutionPolicy Bypass -File scripts\schedule_windows.ps1
```

**macOS/Linux (cron):**
```
0 7 * * * cd /path/to/weather-pipeline && /usr/bin/python3 run_pipeline.py
```

**GitHub Actions:** `.github/workflows/daily-pipeline.yml` runs the tests and
the pipeline every day. It commits the refreshed database and CSVs, and deploys
the HTML dashboard to GitHub Pages.

## Schema

- `dim_city` holds the city, state/UT, state type, region, `capital_of`, coordinates,
  timezone and an `is_active` flag.
- `fact_daily_weather` holds one row per city per day: high/low/mean temperature,
  rain, wind, weather code, a forecast flag, the source and the load time.
- `pipeline_runs` is the audit log.

## Project layout

```
run_pipeline.py          orchestrator / CLI
config.json              cities + settings
pipeline/                extract, transform, load, reports, dashboard, export (CSV)
powerbi/data/            CSVs for Power BI (regenerated each run)
powerbi/POWERBI_GUIDE.md step-by-step Power BI build: model, DAX, layout
powerbi/backgrounds/     SVG page backgrounds used in the Power BI report
.vscode/                 run/debug configs + test discovery for VS Code
sql/schema.sql           DDL
sql/reports/*.sql        report definitions (run in filename order)
dashboard/template.html  dashboard template (data injected at build time)
tests/                   offline unit tests
scripts/                 scheduler setup
```
