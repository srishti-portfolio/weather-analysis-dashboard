"""Export tables to CSV so Power BI (Get Data > Folder / Text/CSV) can read them."""
import csv
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# file name -> query. Every city-level file carries city, state_ut and region so each
# CSV is readable on its own; Power BI can still relate them through dim_city.
EXPORTS = {
    "dim_city": """
        SELECT city_id, name AS city, state_ut, state_type, region, capital_of,
               country, latitude, longitude, timezone
        FROM dim_city WHERE is_active = 1 ORDER BY region, state_ut""",
    "fact_daily_weather": """
        SELECT f.city_id, c.name AS city, c.state_ut, c.region, f.obs_date,
               f.temp_max_c, f.temp_min_c, f.temp_mean_c, f.precip_mm, f.wind_max_kmh,
               f.weather_code, f.is_forecast, f.source, f.loaded_at
        FROM fact_daily_weather f
        JOIN dim_city c ON c.city_id = f.city_id AND c.is_active = 1
        ORDER BY c.name, f.obs_date""",
    "pipeline_runs": "SELECT * FROM pipeline_runs ORDER BY run_id",
    "report_city_summary_30d": "SELECT * FROM report_city_summary_30d",
    "report_daily_trend": "SELECT * FROM report_daily_trend",
    "report_monthly": "SELECT * FROM report_monthly",
    "report_region_monthly": "SELECT * FROM report_region_monthly",
    "report_dry_streaks": "SELECT * FROM report_dry_streaks",
    "report_forecast": "SELECT * FROM report_forecast",
    "report_data_quality": "SELECT * FROM report_data_quality",
}
EXPORT_TABLES = list(EXPORTS)


def export_csv(conn, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, query in EXPORTS.items():
        cur = conn.execute(query)
        headers = [c[0] for c in cur.description]
        path = out_dir / f"{name}.csv"
        # Write to a temp file then swap, so Power BI never reads a half-written CSV.
        tmp = path.with_suffix(".csv.tmp")
        with tmp.open("w", newline="", encoding="utf-8-sig") as f:  # BOM keeps Excel/Power BI happy with UTF-8
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(cur.fetchall())
        tmp.replace(path)
        written.append(path)
    log.info("exported %d CSV files to %s", len(written), out_dir)
    return written
