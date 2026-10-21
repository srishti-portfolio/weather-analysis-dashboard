"""Daily ETL entry point: extract -> transform -> load -> refresh SQL reports -> dashboard + Power BI CSVs.

Usage:
    python run_pipeline.py                     # incremental daily run
    python run_pipeline.py --backfill-days 730 # first run with a longer history
    python run_pipeline.py --reports-only      # rebuild reports + dashboard from the DB
"""
import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

from pipeline import extract, load, reports, transform
from pipeline.dashboard import build_dashboard
from pipeline.export import export_csv

ROOT = Path(__file__).resolve().parent
ARCHIVE_LAG_DAYS = 6  # archive API trails real time; the forecast endpoint covers the gap

log = logging.getLogger("pipeline")


def setup_logging():
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(ROOT / "logs" / "pipeline.log", encoding="utf-8"),
        ],
    )


def plan_city(last_observed, local_today, backfill_days, min_refresh_days):
    """Decide which API calls a city needs. Returns (archive_range or None, past_days)."""
    archive_end = local_today - timedelta(days=ARCHIVE_LAG_DAYS)
    if last_observed is None:
        start = local_today - timedelta(days=backfill_days)
    else:
        start = date.fromisoformat(last_observed) + timedelta(days=1)

    archive_range = None
    gap_days = (local_today - start).days
    if gap_days > extract.MAX_FORECAST_PAST_DAYS and start <= archive_end:
        archive_range = (start, archive_end)
        start = archive_end + timedelta(days=1)

    past_days = max(min_refresh_days, (local_today - start).days + 1)
    return archive_range, min(past_days, extract.MAX_FORECAST_PAST_DAYS)


REQUIRED_CITY_FIELDS = ("name", "state_ut", "region", "latitude", "longitude")


def validate_config(cfg):
    names = [c.get("name") for c in cfg["cities"]]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise ValueError(f"config.json: duplicate city names {sorted(dupes)}")
    for c in cfg["cities"]:
        missing = [f for f in REQUIRED_CITY_FIELDS if c.get(f) in (None, "")]
        if missing:
            raise ValueError(f"config.json: city {c.get('name')!r} is missing {missing}")


def sync_cities(conn, cfg):
    """Make dim_city match config.json: upsert listed cities, deactivate removed ones."""
    ids = {c["name"]: load.upsert_city(conn, c) for c in cfg["cities"]}
    removed = load.deactivate_missing_cities(conn, list(ids))
    if removed:
        log.info("deactivated %d cities no longer in config.json", removed)
    conn.commit()
    return ids


def ingest(conn, cfg, city_ids, backfill_days):
    stats = {"upserted": 0, "rejected": 0, "api_calls": 0, "failed_cities": []}
    local_today = date.today()
    city_today = local_today

    for city in cfg["cities"]:
        try:
            city_today = ingest_city(conn, cfg, city, city_ids[city["name"]], backfill_days, local_today, stats)
        except extract.ExtractError as e:
            # One bad city shouldn't block the other 33; the run is marked 'partial'.
            conn.rollback()
            stats["failed_cities"].append(city["name"])
            log.error("skipping %s: %s", city["name"], e)

    purged = load.purge_stale_forecasts(conn, city_today.isoformat())
    if purged:
        log.info("purged %d stale forecast rows", purged)
    conn.commit()
    return stats


def ingest_city(conn, cfg, city, city_id, backfill_days, local_today, stats):
    """Fetch and load one city. Returns 'today' as reported by the API for that city."""
    last = load.last_observed_date(conn, city_id)
    archive_range, past_days = plan_city(last, local_today, backfill_days, cfg["min_refresh_days"])
    rejected = []

    if archive_range:
        payload = extract.fetch_archive(city, *archive_range)
        stats["api_calls"] += 1
        rows, bad = transform.to_rows(payload, "archive", today=local_today)
        stats["upserted"] += load.upsert_weather(conn, city_id, rows)
        rejected += bad

    payload = extract.fetch_recent_and_forecast(city, past_days, cfg["forecast_days"])
    stats["api_calls"] += 1
    dates = payload.get("daily", {}).get("time", [])
    # The forecast endpoint returns past_days, then today in the city's timezone.
    city_today = date.fromisoformat(dates[past_days]) if len(dates) > past_days else local_today
    rows, bad = transform.to_rows(payload, "forecast", today=city_today)
    stats["upserted"] += load.upsert_weather(conn, city_id, rows)
    rejected += bad

    stats["rejected"] += len(rejected)
    for r in rejected:
        log.warning("rejected %s %s: %s", city["name"], r["obs_date"], r["reject_reason"])
    conn.commit()
    return city_today


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=ROOT / "config.json", type=Path)
    parser.add_argument("--backfill-days", type=int, help="history to load on first run (overrides config)")
    parser.add_argument("--reports-only", action="store_true", help="skip API calls")
    args = parser.parse_args(argv)

    setup_logging()
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    validate_config(cfg)
    extract.set_request_delay(cfg.get("request_delay_seconds", 0))
    conn = load.connect(ROOT / cfg["database"])
    run_id = load.start_run(conn)
    stats = {"upserted": 0, "rejected": 0, "api_calls": 0, "failed_cities": []}

    try:
        city_ids = sync_cities(conn, cfg)
        if not args.reports_only:
            stats = ingest(conn, cfg, city_ids, args.backfill_days or cfg["backfill_days"])
            log.info("ingest done: %s", stats)
        refreshed = reports.refresh_reports(conn)

        failed = stats["failed_cities"]
        if failed and len(failed) == len(cfg["cities"]):
            raise extract.ExtractError("every city failed to download")
        status = "partial" if failed else "success"
        error = f"failed cities: {', '.join(failed)}" if failed else None
        load.finish_run(conn, run_id, status, stats["upserted"], stats["rejected"], stats["api_calls"], error)

        out = build_dashboard(conn, ROOT / cfg["dashboard_output"], cfg.get("default_compare_cities", []))
        export_csv(conn, ROOT / cfg["csv_output"])
        log.info("refreshed %d reports, dashboard written to %s", len(refreshed), out)
    except Exception as e:
        conn.rollback()
        load.finish_run(conn, run_id, "failed", stats["upserted"], stats["rejected"], stats["api_calls"], str(e))
        log.exception("pipeline run %d failed", run_id)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
