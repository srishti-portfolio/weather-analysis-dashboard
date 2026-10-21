"""Offline tests: no network calls. Run with `python -m unittest`."""
import csv
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from pipeline import load, reports, transform
from run_pipeline import plan_city, validate_config

CITY = {"name": "Testville", "state_ut": "Test State", "state_type": "State", "region": "South",
        "capital_of": "Test State", "latitude": 1.0, "longitude": 2.0}
OTHER = {"name": "Otherpur", "state_ut": "Other UT", "state_type": "Union Territory", "region": "North",
         "capital_of": "Other UT", "latitude": 3.0, "longitude": 4.0}


def payload(dates, tmax, tmin, rain):
    return {"daily": {
        "time": dates,
        "temperature_2m_max": tmax,
        "temperature_2m_min": tmin,
        "temperature_2m_mean": [None] * len(dates),
        "precipitation_sum": rain,
        "wind_speed_10m_max": [10.0] * len(dates),
        "weather_code": [0] * len(dates),
    }}


class TransformTests(unittest.TestCase):
    def test_rows_flagged_and_mean_derived(self):
        p = payload(["2026-01-01", "2026-01-02"], [30.0, 31.0], [20.0, 21.0], [0.0, 5.0])
        rows, bad = transform.to_rows(p, "forecast", today=date(2026, 1, 2))
        self.assertEqual(bad, [])
        self.assertEqual(rows[0]["temp_mean_c"], 25.0)
        self.assertEqual([r["is_forecast"] for r in rows], [0, 1])  # today counts as forecast

    def test_invalid_rows_rejected(self):
        p = payload(["2026-01-01", "2026-01-02", "2026-01-03"], [10.0, None, 20.0], [15.0, None, 10.0], [0, 0, -1])
        rows, bad = transform.to_rows(p, "archive", today=date(2026, 2, 1))
        self.assertEqual(rows, [])
        self.assertEqual([b["reject_reason"] for b in bad],
                         ["temp_min > temp_max", "all temperatures null", "negative precipitation"])


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.conn = load.connect(":memory:")
        self.city_id = load.upsert_city(self.conn, CITY)

    def test_upsert_is_idempotent_and_overwrites_forecast(self):
        p = payload(["2026-01-01", "2026-01-02"], [30.0, 31.0], [20.0, 21.0], [0.0, 5.0])
        rows, _ = transform.to_rows(p, "forecast", today=date(2026, 1, 2))
        load.upsert_weather(self.conn, self.city_id, rows)
        load.upsert_weather(self.conn, self.city_id, rows)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM fact_daily_weather").fetchone()[0], 2)

        # Next day: the forecast row becomes an actual with new values.
        rows, _ = transform.to_rows(payload(["2026-01-02"], [33.0], [22.0], [1.0]), "forecast", today=date(2026, 1, 3))
        load.upsert_weather(self.conn, self.city_id, rows)
        r = self.conn.execute("SELECT temp_max_c, is_forecast FROM fact_daily_weather WHERE obs_date='2026-01-02'").fetchone()
        self.assertEqual(tuple(r), (33.0, 0))

    def test_reports_build_on_small_dataset(self):
        dates = [f"2026-01-{d:02d}" for d in range(1, 11)]
        rain = [0, 0, 0, 5, 0, 0, 0, 0, 2, 0]  # longest dry run = days 5-8
        rows, _ = transform.to_rows(payload(dates, [30.0] * 10, [20.0] * 10, rain), "archive", today=date(2026, 2, 1))
        load.upsert_weather(self.conn, self.city_id, rows)
        reports.refresh_reports(self.conn)

        dry = reports.fetch_table(self.conn, "report_dry_streaks")[0]
        self.assertEqual((dry["start_date"], dry["end_date"], dry["length_days"]), ("2026-01-05", "2026-01-08", 4))
        summary = reports.fetch_table(self.conn, "report_city_summary_30d")[0]
        self.assertEqual(summary["rainy_days"], 2)
        quality = reports.fetch_table(self.conn, "report_data_quality")[0]
        self.assertEqual(quality["missing_days"], 0)


class CityTests(unittest.TestCase):
    def setUp(self):
        self.conn = load.connect(":memory:")

    def test_removed_city_is_hidden_from_reports(self):
        rows, _ = transform.to_rows(payload(["2026-01-01"], [30.0], [20.0], [0.0]), "archive", today=date(2026, 2, 1))
        for city in (CITY, OTHER):
            load.upsert_weather(self.conn, load.upsert_city(self.conn, city), rows)

        load.deactivate_missing_cities(self.conn, [CITY["name"]])
        reports.refresh_reports(self.conn)
        cities = [r["city"] for r in reports.fetch_table(self.conn, "report_city_summary_30d")]
        self.assertEqual(cities, ["Testville"])

        load.upsert_city(self.conn, OTHER)  # re-adding it to config reactivates it
        reports.refresh_reports(self.conn)
        self.assertEqual(len(reports.fetch_table(self.conn, "report_city_summary_30d")), 2)

    def test_old_database_gets_new_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "old.db"
            old = sqlite3.connect(db)
            old.execute("CREATE TABLE dim_city (city_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,"
                        " country TEXT, latitude REAL NOT NULL, longitude REAL NOT NULL, timezone TEXT NOT NULL)")
            old.commit(); old.close()

            conn = load.connect(db)
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(dim_city)")}
            self.assertTrue({"state_ut", "state_type", "region", "capital_of", "is_active"} <= cols)
            load.upsert_city(conn, CITY)
            self.assertEqual(conn.execute("SELECT region FROM dim_city").fetchone()[0], "South")
            conn.close()

    def test_config_validation(self):
        validate_config({"cities": [CITY, OTHER]})
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_config({"cities": [CITY, CITY]})
        with self.assertRaisesRegex(ValueError, "region"):
            validate_config({"cities": [{**CITY, "region": ""}]})


class ExportTests(unittest.TestCase):
    def test_csv_export_writes_every_table_with_state_and_region(self):
        from pipeline.export import EXPORT_TABLES, export_csv

        conn = load.connect(":memory:")
        city_id = load.upsert_city(conn, CITY)
        rows, _ = transform.to_rows(payload(["2026-01-01"], [30.0], [20.0], [0.0]), "archive", today=date(2026, 2, 1))
        load.upsert_weather(conn, city_id, rows)
        reports.refresh_reports(conn)

        with tempfile.TemporaryDirectory() as tmp:
            paths = export_csv(conn, tmp)
            self.assertEqual(sorted(p.stem for p in paths), sorted(EXPORT_TABLES))
            for p in paths:
                if p.stem == "pipeline_runs":
                    continue
                with p.open(encoding="utf-8-sig") as f:
                    header = next(csv.reader(f))
                self.assertIn("region", header, p.name)
                if p.stem != "report_region_monthly":
                    self.assertIn("state_ut", header, p.name)
            with (Path(tmp) / "fact_daily_weather.csv").open(encoding="utf-8-sig") as f:
                data = list(csv.DictReader(f))
            self.assertEqual((data[0]["obs_date"], data[0]["state_ut"], data[0]["region"]),
                             ("2026-01-01", "Test State", "South"))
            self.assertEqual(float(data[0]["temp_max_c"]), 30.0)


class PlanTests(unittest.TestCase):
    def test_first_run_uses_archive(self):
        archive, past = plan_city(None, date(2026, 10, 12), 365, 7)
        self.assertEqual(archive, (date(2025, 10, 12), date(2026, 10, 6)))
        self.assertEqual(past, 7)

    def test_daily_run_only_hits_forecast(self):
        archive, past = plan_city("2026-10-11", date(2026, 10, 12), 365, 7)
        self.assertIsNone(archive)
        self.assertEqual(past, 7)

    def test_missed_two_weeks_widens_window(self):
        archive, past = plan_city("2026-09-28", date(2026, 10, 12), 365, 7)
        self.assertIsNone(archive)
        self.assertEqual(past, 14)


if __name__ == "__main__":
    unittest.main()
