"""SQLite access across the two Catalyst databases.

  db/catalyst.db  — cohort tables + cohort views. Rebuilt from scratch by
                    db/load_cohort.py; treat as read-only from the API.
  db/app.db       — app-owned state (triage, audit, patient-app writes).
                    Never touched by the loader, so user writes survive a
                    cohort reload.

get_connection() opens catalyst.db as `main` and ATTACHes app.db as `app`, so:

    SELECT * FROM v_episode                  -- cohort, unqualified
    SELECT * FROM app.queue_item             -- app-owned, prefixed

That split keeps every pre-split cohort query working untouched. Two rules
follow from it:

  • SQLite cannot enforce foreign keys across attached databases, so app.db
    references patient_id / fin softly. Intra-app.db FKs still apply.
  • No cross-database views. Views live with their tables; joins spanning both
    databases are written in router SQL.

Override paths with CATALYST_DB / CATALYST_APP_DB.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.environ.get("CATALYST_DB", REPO_ROOT / "db" / "catalyst.db"))
APP_DB_PATH = Path(os.environ.get("CATALYST_APP_DB", REPO_ROOT / "db" / "app.db"))


def get_connection() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise RuntimeError(
            f"{DB_PATH} not found — run `python3 db/load_cohort.py` first"
        )
    if not APP_DB_PATH.exists():
        raise RuntimeError(
            f"{APP_DB_PATH} not found — run `python3 db/migrate_app.py` first"
        )
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("ATTACH DATABASE ? AS app", (str(APP_DB_PATH),))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_setting(key: str) -> Optional[str]:
    """Read an app_setting value, or None if it (or the database) is missing.

    Tolerant by design: clock.py calls this during startup, before the
    migration may have run, and must fall back rather than crash.
    """
    try:
        conn = get_connection()
    except RuntimeError:
        return None
    try:
        row = conn.execute(
            "SELECT value FROM app.app_setting WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None
    except sqlite3.OperationalError:
        # app_setting missing → migration not applied yet; caller falls back
        return None
    finally:
        conn.close()
