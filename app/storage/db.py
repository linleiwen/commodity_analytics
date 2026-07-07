"""SQLite persistence helpers.

A thin, dependency-free wrapper around ``sqlite3`` plus pandas read helpers. The schema
lives in ``schema.sql``; everything here is idempotent so the pipeline can be re-run.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

import pandas as pd

from app import settings


def utcnow() -> str:
    """ISO-8601 UTC timestamp used consistently across all tables."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Yield a SQLite connection with row access by name and foreign keys enabled."""
    settings.ensure_dirs()
    path = db_path or settings.DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> Path:
    """Create all tables from ``schema.sql``. Safe to run repeatedly."""
    path = db_path or settings.DB_PATH
    settings.ensure_dirs()
    schema_sql = settings.SCHEMA_PATH.read_text(encoding="utf-8")
    with connect(path) as conn:
        conn.executescript(schema_sql)
    return path


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    cur = conn.execute(f"PRAGMA table_info({table});")
    return [row["name"] for row in cur.fetchall()]


def upsert(conn: sqlite3.Connection, table: str, row: dict[str, Any]) -> None:
    """Insert-or-replace a single row, keeping only columns that exist in the table."""
    cols = _table_columns(conn, table)
    filtered = {k: row.get(k) for k in cols if k in row}
    if not filtered:
        return
    placeholders = ", ".join("?" for _ in filtered)
    col_sql = ", ".join(filtered.keys())
    sql = f"INSERT OR REPLACE INTO {table} ({col_sql}) VALUES ({placeholders})"
    conn.execute(sql, tuple(filtered.values()))


def upsert_many(conn: sqlite3.Connection, table: str, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    for row in rows:
        upsert(conn, table, row)
        count += 1
    return count


def ensure_run(conn: sqlite3.Connection, run_id: str, notes: str = "") -> None:
    existing = conn.execute("SELECT run_id FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    now = utcnow()
    if existing:
        conn.execute("UPDATE runs SET updated_at = ? WHERE run_id = ?", (now, run_id))
    else:
        conn.execute(
            "INSERT INTO runs (run_id, created_at, updated_at, notes) VALUES (?, ?, ?, ?)",
            (run_id, now, now, notes),
        )


def set_run_assumptions(conn: sqlite3.Connection, run_id: str, assumptions_json: str) -> None:
    ensure_run(conn, run_id)
    conn.execute(
        "UPDATE runs SET assumptions_json = ?, updated_at = ? WHERE run_id = ?",
        (assumptions_json, utcnow(), run_id),
    )


def log_source(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    row.setdefault("observed_at", utcnow())
    upsert(conn, "source_log", row)


def read_df(sql: str, params: tuple = (), db_path: Path | None = None) -> pd.DataFrame:
    """Run a SELECT and return a DataFrame."""
    path = db_path or settings.DB_PATH
    if not Path(path).exists():
        return pd.DataFrame()
    with sqlite3.connect(path) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def read_table(table: str, run_id: str | None = None, db_path: Path | None = None) -> pd.DataFrame:
    if run_id is None:
        return read_df(f"SELECT * FROM {table}", db_path=db_path)
    return read_df(f"SELECT * FROM {table} WHERE run_id = ?", (run_id,), db_path=db_path)


def read_products(db_path: Path | None = None) -> pd.DataFrame:
    return read_df("SELECT * FROM product_master", db_path=db_path)


def clear_run(conn: sqlite3.Connection, table: str, run_id: str) -> None:
    """Delete rows for a given run so a step can be re-run cleanly."""
    conn.execute(f"DELETE FROM {table} WHERE run_id = ?", (run_id,))


def update_product_fields(conn: sqlite3.Connection, product_id: str, fields: dict[str, Any]) -> None:
    """Merge-update Product Master: only overwrite columns whose new value is not None."""
    cols = _table_columns(conn, "product_master")
    updates = {k: v for k, v in fields.items() if k in cols and v is not None}
    if not updates or not product_id:
        return
    updates["updated_at"] = utcnow()
    set_sql = ", ".join(f"{k} = ?" for k in updates)
    params = tuple(updates.values()) + (product_id,)
    conn.execute(f"UPDATE product_master SET {set_sql} WHERE product_id = ?", params)
