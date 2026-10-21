"""Refresh SQL-driven report tables by executing every file in sql/reports in order."""
import logging
from pathlib import Path

log = logging.getLogger(__name__)
REPORTS_DIR = Path(__file__).resolve().parent.parent / "sql" / "reports"


def refresh_reports(conn):
    refreshed = []
    for sql_file in sorted(REPORTS_DIR.glob("*.sql")):
        conn.executescript(sql_file.read_text())
        refreshed.append(sql_file.stem)
        log.info("refreshed report %s", sql_file.stem)
    conn.commit()
    return refreshed


def fetch_table(conn, table):
    cur = conn.execute(f"SELECT * FROM {table}")
    return [dict(r) for r in cur.fetchall()]
