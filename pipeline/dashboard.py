"""Render the report tables into a self-contained HTML dashboard."""
import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline.reports import fetch_table

TEMPLATE = Path(__file__).resolve().parent.parent / "dashboard" / "template.html"
PLACEHOLDER = "/*__DATA__*/null"
REGION_ORDER = ["North", "Central", "East", "Northeast", "West", "South"]


def collect(conn, compare_cities=()):
    runs = conn.execute(
        "SELECT run_id, started_at, finished_at, status, rows_upserted, rows_rejected, api_calls, error "
        "FROM pipeline_runs ORDER BY run_id DESC LIMIT 10"
    ).fetchall()
    cities = [dict(r) for r in conn.execute(
        "SELECT name AS city, state_ut, state_type, region, capital_of FROM dim_city "
        "WHERE is_active = 1 ORDER BY name"
    )]
    names = {c["city"] for c in cities}
    present = {c["region"] for c in cities}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cities": cities,
        "regions": [r for r in REGION_ORDER if r in present] + sorted(present - set(REGION_ORDER) - {None}),
        "compare_default": [c for c in compare_cities if c in names][:4],
        "states_covered": len({s.strip() for c in cities for s in (c["capital_of"] or c["state_ut"] or "").split(";") if s.strip()}),
        "total_rows": conn.execute(
            "SELECT COUNT(*) FROM fact_daily_weather f JOIN dim_city c ON c.city_id = f.city_id "
            "WHERE f.is_forecast = 0 AND c.is_active = 1").fetchone()[0],
        "summary": fetch_table(conn, "report_city_summary_30d"),
        "trend": fetch_table(conn, "report_daily_trend"),
        "monthly": fetch_table(conn, "report_monthly"),
        "region_monthly": fetch_table(conn, "report_region_monthly"),
        "dry": fetch_table(conn, "report_dry_streaks"),
        "forecast": fetch_table(conn, "report_forecast"),
        "quality": fetch_table(conn, "report_data_quality"),
        "runs": [dict(r) for r in runs],
    }


def build_dashboard(conn, out_path, compare_cities=()):
    data = json.dumps(collect(conn, compare_cities), separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace(PLACEHOLDER, data)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
