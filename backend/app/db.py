"""SQLite access for db/catalyst.db (read-mostly; app-owned writes in M4+)."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.environ.get("CATALYST_DB", REPO_ROOT / "db" / "catalyst.db"))


def get_connection() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise RuntimeError(
            f"{DB_PATH} not found — run `python3 db/load_cohort.py` first"
        )
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_setting(key: str) -> Optional[str]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT value FROM app_setting WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None
    except sqlite3.OperationalError:
        # app_setting missing → migration not applied yet; caller falls back
        return None
    finally:
        conn.close()
