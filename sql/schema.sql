-- Star-ish schema: one dimension (city), one fact (daily weather), one audit table.

CREATE TABLE IF NOT EXISTS dim_city (
    city_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    state_ut    TEXT,                              -- state or union territory the city belongs to
    state_type  TEXT,                              -- 'State' | 'Union Territory'
    region      TEXT,                              -- North | South | East | West | Central | Northeast
    capital_of  TEXT,                              -- every state/UT this city is capital of (e.g. Chandigarh)
    country     TEXT,
    latitude    REAL    NOT NULL,
    longitude   REAL    NOT NULL,
    timezone    TEXT    NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 1         -- 0 = removed from config.json; history kept, hidden from reports
);

CREATE TABLE IF NOT EXISTS fact_daily_weather (
    city_id         INTEGER NOT NULL REFERENCES dim_city(city_id),
    obs_date        TEXT    NOT NULL,              -- ISO yyyy-mm-dd, local to the city
    temp_max_c      REAL,
    temp_min_c      REAL,
    temp_mean_c     REAL,
    precip_mm       REAL,
    wind_max_kmh    REAL,
    weather_code    INTEGER,
    is_forecast     INTEGER NOT NULL DEFAULT 0,    -- 1 = future date; overwritten once actuals arrive
    source          TEXT    NOT NULL,              -- 'archive' | 'forecast'
    loaded_at       TEXT    NOT NULL,
    PRIMARY KEY (city_id, obs_date)
);

CREATE INDEX IF NOT EXISTS ix_fact_date ON fact_daily_weather(obs_date);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    status          TEXT NOT NULL,                 -- running | success | failed
    rows_upserted   INTEGER DEFAULT 0,
    rows_rejected   INTEGER DEFAULT 0,
    api_calls       INTEGER DEFAULT 0,
    error           TEXT
);
