#!/usr/bin/env python3
"""Apply app-owned tables + views (db/app_tables.sql) to catalyst.db.

Idempotent: tables are CREATE IF NOT EXISTS (user writes survive), views are
DROP + CREATE (no data). Safe to run any number of times, and load_cohort.py
calls apply_app_tables() automatically after every cohort load.

Also applies additive ALTER TABLE column upgrades for queue_item so existing
DBs pick up M6 framework fields without dropping user/demo rows.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_TABLES_SQL = Path(__file__).resolve().parent / "app_tables.sql"
DEFAULT_DB = REPO_ROOT / "db" / "catalyst.db"

# Additive columns for queue_item when the table already existed from an
# earlier migration (CREATE IF NOT EXISTS will not reshape it).
QUEUE_ITEM_COLUMNS = [
    ("demo_key", "TEXT UNIQUE"),
    ("kind", "TEXT NOT NULL DEFAULT 'manual'"),
    ("severity", "TEXT NOT NULL DEFAULT 'yellow'"),
    ("title", "TEXT NOT NULL DEFAULT ''"),
    ("summary", "TEXT"),
    ("source_type", "TEXT"),
    ("source_id", "TEXT"),
    ("resolution_action", "TEXT"),
]


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def _upgrade_queue_item(conn: sqlite3.Connection) -> None:
    cols = _table_columns(conn, "queue_item")
    if not cols:
        return
    for name, decl in QUEUE_ITEM_COLUMNS:
        if name in cols:
            continue
        # SQLite cannot add UNIQUE via ALTER in one step for existing tables;
        # demo_key uniqueness is enforced by a unique index below.
        safe_decl = decl.replace(" UNIQUE", "")
        conn.execute(f"ALTER TABLE queue_item ADD COLUMN {name} {safe_decl}")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_queue_fin ON queue_item(fin, status)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_demo_key "
        "ON queue_item(demo_key) WHERE demo_key IS NOT NULL"
    )


def apply_app_tables(db_path: Path = DEFAULT_DB) -> None:
    if not db_path.exists():
        raise FileNotFoundError(
            f"{db_path} not found — run `python3 db/load_cohort.py` first"
        )
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(APP_TABLES_SQL.read_text(encoding="utf-8"))
        _upgrade_queue_item(conn)
        conn.commit()
    finally:
        conn.close()

    # Demo triage alerts (idempotent INSERT OR IGNORE by demo_key).
    try:
        from seed_queue_demo import seed_queue_demo

        seed_queue_demo(db_path)
    except Exception:
        # Seed is best-effort; missing cohort FINs should not fail migrate.
        pass


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Apply app tables/views to catalyst.db")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite path")
    args = parser.parse_args()
    apply_app_tables(args.db)
    print(f"Applied {APP_TABLES_SQL.name} to {args.db}")
