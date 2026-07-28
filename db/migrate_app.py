#!/usr/bin/env python3
"""Apply the two-database migration: app-owned tables + cohort views.

  db/app_tables.sql   → db/app.db       (app-owned state; survives reloads)
  db/cohort_views.sql → db/catalyst.db  (cohort-derived views)

Idempotent: app tables are CREATE IF NOT EXISTS and never dropped, views are
DROP + CREATE. Safe to run any number of times. db/load_cohort.py calls
apply_app_tables() after every cohort load — because app state now lives in a
separate file, a cohort rebuild no longer destroys patient or triage writes.

Also seeds the static reference catalogs (PT exercises, checklist items) and
applies additive ALTER TABLE upgrades so pre-split databases pick up new
columns without dropping rows.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_DIR = Path(__file__).resolve().parent
APP_TABLES_SQL = DB_DIR / "app_tables.sql"
COHORT_VIEWS_SQL = DB_DIR / "cohort_views.sql"
DEFAULT_DB = REPO_ROOT / "db" / "catalyst.db"
DEFAULT_APP_DB = REPO_ROOT / "db" / "app.db"

# Additive columns for tables that may predate a change. CREATE IF NOT EXISTS
# will not reshape an existing table, so upgrades land here.
ADDITIVE_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "queue_item": [
        ("demo_key", "TEXT UNIQUE"),
        ("kind", "TEXT NOT NULL DEFAULT 'manual'"),
        ("severity", "TEXT NOT NULL DEFAULT 'yellow'"),
        ("title", "TEXT NOT NULL DEFAULT ''"),
        ("summary", "TEXT"),
        ("source_type", "TEXT"),
        ("source_id", "TEXT"),
        ("resolution_action", "TEXT"),
    ],
}


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _apply_additive_columns(conn: sqlite3.Connection) -> None:
    for table, columns in ADDITIVE_COLUMNS.items():
        existing = _table_columns(conn, table)
        if not existing:
            continue
        for name, decl in columns:
            if name in existing:
                continue
            # SQLite cannot ADD COLUMN ... UNIQUE; enforce via index instead.
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN {name} {decl.replace(' UNIQUE', '')}"
            )
    if _table_columns(conn, "queue_item"):
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_demo_key "
            "ON queue_item(demo_key) WHERE demo_key IS NOT NULL"
        )


def _seed_catalogs(conn: sqlite3.Connection) -> None:
    """Load the static PT exercise + checklist catalogs into app.db.

    Definitions live in backend/app/catalog.py so the API and the seeder cannot
    drift. INSERT OR REPLACE keyed on the natural key: reference data has no
    user writes to protect, and this lets catalog edits propagate.
    """
    backend = REPO_ROOT / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    try:
        from app.catalog import CHECKLIST_ITEMS, PT_EXERCISES
    except Exception as exc:  # pragma: no cover - catalog import is best-effort
        print(f"  (skipped catalog seed: {exc})")
        return

    for ex in PT_EXERCISES:
        conn.execute(
            """
            INSERT INTO pt_exercise (
                code, phase, name, description, video_url,
                default_sets, default_reps, weight_bearing_note, sort_order
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                phase = excluded.phase,
                name = excluded.name,
                description = excluded.description,
                video_url = excluded.video_url,
                default_sets = excluded.default_sets,
                default_reps = excluded.default_reps,
                weight_bearing_note = excluded.weight_bearing_note,
                sort_order = excluded.sort_order
            """,
            (
                ex["code"],
                ex["phase"],
                ex["name"],
                ex.get("description"),
                ex.get("video_url"),
                ex.get("default_sets"),
                ex.get("default_reps"),
                ex.get("weight_bearing_note"),
                ex.get("sort_order", 0),
            ),
        )

    for item in CHECKLIST_ITEMS:
        conn.execute(
            """
            INSERT INTO checklist_item (
                checklist_code, item_code, phase, label, help_text,
                critical, sort_order
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(checklist_code, item_code) DO UPDATE SET
                phase = excluded.phase,
                label = excluded.label,
                help_text = excluded.help_text,
                critical = excluded.critical,
                sort_order = excluded.sort_order
            """,
            (
                item["checklist_code"],
                item["item_code"],
                item["phase"],
                item["label"],
                item.get("help_text"),
                1 if item.get("critical") else 0,
                item.get("sort_order", 0),
            ),
        )


def apply_app_tables(
    db_path: Path = DEFAULT_DB, app_db_path: Path | None = None
) -> None:
    """Apply cohort views to db_path and app-owned tables to app_db_path."""
    app_db_path = app_db_path or (db_path.parent / "app.db")

    # 1. App-owned state (its own file; created on first run).
    app_conn = sqlite3.connect(app_db_path)
    try:
        app_conn.executescript(APP_TABLES_SQL.read_text(encoding="utf-8"))
        _apply_additive_columns(app_conn)
        _seed_catalogs(app_conn)
        app_conn.commit()
    finally:
        app_conn.close()

    # 2. Cohort-derived views (require the cohort tables to exist).
    if db_path.exists():
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(COHORT_VIEWS_SQL.read_text(encoding="utf-8"))
            conn.commit()
        finally:
            conn.close()

    # 3. Demo triage alerts (idempotent INSERT OR IGNORE by demo_key). Needs
    #    both databases: FIN/patient validation reads the cohort.
    try:
        from seed_queue_demo import seed_queue_demo

        seed_queue_demo(db_path, app_db_path)
    except Exception:
        # Best-effort: a missing cohort should not fail the migration.
        pass


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Apply app tables (app.db) and cohort views (catalyst.db)"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="cohort SQLite path")
    parser.add_argument(
        "--app-db", type=Path, default=DEFAULT_APP_DB, help="app-owned SQLite path"
    )
    args = parser.parse_args()
    apply_app_tables(args.db, args.app_db)
    print(f"Applied {APP_TABLES_SQL.name} → {args.app_db}")
    print(f"Applied {COHORT_VIEWS_SQL.name} → {args.db}")
