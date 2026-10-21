"""Load: idempotent upserts into SQLite plus a run-audit table."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path):
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript((ROOT / "sql" / "schema.sql").read_text())
    migrate(conn)
    return conn


# Columns added after the first release. CREATE TABLE IF NOT EXISTS won't add them
# to an existing database, so add any that are missing.
DIM_CITY_MIGRATIONS = {
    "state_ut": "TEXT",
    "state_type": "TEXT",
    "region": "TEXT",
    "capital_of": "TEXT",
    "is_active": "INTEGER NOT NULL DEFAULT 1",
}


def migrate(conn):
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(dim_city)")}
    for col, ddl in DIM_CITY_MIGRATIONS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE dim_city ADD COLUMN {col} {ddl}")
    conn.commit()


CITY_DEFAULTS = {"country": "IN", "timezone": "Asia/Kolkata", "state_ut": None,
                 "state_type": None, "region": None, "capital_of": None}


def upsert_city(conn, city):
    conn.execute(
        """INSERT INTO dim_city (name, state_ut, state_type, region, capital_of, country,
                                 latitude, longitude, timezone, is_active)
           VALUES (:name, :state_ut, :state_type, :region, :capital_of, :country,
                   :latitude, :longitude, :timezone, 1)
           ON CONFLICT(name) DO UPDATE SET
             state_ut=excluded.state_ut, state_type=excluded.state_type,
             region=excluded.region, capital_of=excluded.capital_of,
             country=excluded.country, latitude=excluded.latitude,
             longitude=excluded.longitude, timezone=excluded.timezone, is_active=1""",
        {**CITY_DEFAULTS, **city},
    )
    return conn.execute("SELECT city_id FROM dim_city WHERE name = ?", (city["name"],)).fetchone()[0]


def deactivate_missing_cities(conn, active_names):
    """Cities removed from config.json keep their history but drop out of the reports."""
    placeholders = ",".join("?" * len(active_names))
    return conn.execute(
        f"UPDATE dim_city SET is_active = 0 WHERE is_active = 1 AND name NOT IN ({placeholders})",
        list(active_names),
    ).rowcount


def last_observed_date(conn, city_id):
    row = conn.execute(
        "SELECT MAX(obs_date) FROM fact_daily_weather WHERE city_id = ? AND is_forecast = 0",
        (city_id,),
    ).fetchone()
    return row[0]


def upsert_weather(conn, city_id, rows):
    """Insert or overwrite by (city_id, obs_date). Re-running is safe."""
    loaded_at = now_iso()
    conn.executemany(
        """INSERT INTO fact_daily_weather
             (city_id, obs_date, temp_max_c, temp_min_c, temp_mean_c, precip_mm,
              wind_max_kmh, weather_code, is_forecast, source, loaded_at)
           VALUES (:city_id, :obs_date, :temp_max_c, :temp_min_c, :temp_mean_c, :precip_mm,
                   :wind_max_kmh, :weather_code, :is_forecast, :source, :loaded_at)
           ON CONFLICT(city_id, obs_date) DO UPDATE SET
             temp_max_c=excluded.temp_max_c, temp_min_c=excluded.temp_min_c,
             temp_mean_c=excluded.temp_mean_c, precip_mm=excluded.precip_mm,
             wind_max_kmh=excluded.wind_max_kmh, weather_code=excluded.weather_code,
             is_forecast=excluded.is_forecast, source=excluded.source,
             loaded_at=excluded.loaded_at""",
        [{**r, "city_id": city_id, "loaded_at": loaded_at} for r in rows],
    )
    return len(rows)


def purge_stale_forecasts(conn, today_iso):
    """Drop forecast rows for past dates that never received actuals."""
    return conn.execute(
        "DELETE FROM fact_daily_weather WHERE is_forecast = 1 AND obs_date < ?", (today_iso,)
    ).rowcount


def start_run(conn):
    cur = conn.execute(
        "INSERT INTO pipeline_runs (started_at, status) VALUES (?, 'running')", (now_iso(),)
    )
    conn.commit()
    return cur.lastrowid


def finish_run(conn, run_id, status, upserted=0, rejected=0, api_calls=0, error=None):
    conn.execute(
        """UPDATE pipeline_runs SET finished_at=?, status=?, rows_upserted=?,
             rows_rejected=?, api_calls=?, error=? WHERE run_id=?""",
        (now_iso(), status, upserted, rejected, api_calls, error, run_id),
    )
    conn.commit()
