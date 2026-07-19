#!/usr/bin/env python3
"""Seed demo triage queue items for the SHFFT dashboard (M6 framework).

Idempotent: each row has a stable demo_key; INSERT OR IGNORE leaves resolved
user work alone and only fills missing keys. Re-run after migrate_app.py.

  python3 db/migrate_app.py && python3 db/seed_queue_demo.py
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "db" / "catalyst.db"

# Real cohort FINs / patient_ids — stories aligned with mockup archetypes.
DEMO_ITEMS = [
    {
        "demo_key": "demo-chen-readmit-local",
        "kind": "readmit_local",
        "severity": "red",
        "title": "SOB after pneumonia readmit",
        "summary": "Anchor readmit FIN 005102 · pneumonia · Memorial General",
        "source_type": "encounter",
        "source_id": "005102",
        "patient_id": 1,
        "fin": "004821",
        "priority": 10,
        "assigned_role": "Ortho navigator",
    },
    {
        "demo_key": "demo-porter-outside-hie",
        "kind": "readmit_outside",
        "severity": "yellow",
        "title": "Outside bounce (HIE ADT)",
        "summary": "Mercy General · A01 admit · near real-time HIE alert",
        "source_type": "hie_adt_alert",
        "source_id": None,
        "patient_id": 5,
        "fin": "005620",
        "priority": 20,
        "assigned_role": "Case management",
    },
    {
        "demo_key": "demo-hassan-outside-hie",
        "kind": "readmit_outside",
        "severity": "red",
        "title": "Outside admit — Mercy General",
        "summary": "HIE A01 at competitor CCN 140010 during episode window",
        "source_type": "hie_adt_alert",
        "source_id": None,
        "patient_id": 19,
        "fin": "006772",
        "priority": 15,
        "assigned_role": "Case management",
    },
    {
        "demo_key": "demo-ortiz-snf-watch",
        "kind": "app_symptom",
        "severity": "yellow",
        "title": "SNF respiratory watch",
        "summary": "Facility-proxy: productive cough reported by SNF liaison",
        "source_type": None,
        "source_id": None,
        "patient_id": 6,
        "fin": "005700",
        "priority": 30,
        "assigned_role": "SNF liaison",
    },
    {
        "demo_key": "demo-obrien-checkin-miss",
        "kind": "app_checkin_missed",
        "severity": "yellow",
        "title": "Missed daily check-in",
        "summary": "No patient/caregiver check-in in 24h (SNF pathway — sparse expected)",
        "source_type": None,
        "source_id": None,
        "patient_id": 3,
        "fin": "005190",
        "priority": 40,
        "assigned_role": "Ortho navigator",
    },
    {
        "demo_key": "demo-pcp-gap-005970",
        "kind": "pcp_gap",
        "severity": "yellow",
        "title": "PCP gap — never scheduled",
        "summary": "TEAM primary-care referral on file with no appointment datetime",
        "source_type": "referral",
        "source_id": None,
        "patient_id": None,  # filled from v_episode
        "fin": "005970",
        "priority": 35,
        "assigned_role": "Case management",
    },
    {
        "demo_key": "demo-baptiste-claims",
        "kind": "readmit_outside",
        "severity": "yellow",
        "title": "Outside claim arrived (lagged)",
        "summary": "Medicare claims feed · competitor CCN — claims-only visibility",
        "source_type": "medicare_claim_line",
        "source_id": None,
        "patient_id": 29,
        "fin": "007681",
        "priority": 45,
        "assigned_role": "Case management",
    },
    {
        "demo_key": "demo-chen-app-symptom",
        "kind": "app_symptom",
        "severity": "red",
        "title": "Caregiver check-in: SOB, pain 5/10",
        "summary": "App symptom flag after local pneumonia readmit",
        "source_type": "signal_event",
        "source_id": None,
        "patient_id": 1,
        "fin": "004821",
        "priority": 5,
        "assigned_role": "Ortho navigator",
    },
]


def seed_queue_demo(db_path: Path = DEFAULT_DB) -> int:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    inserted = 0
    try:
        for item in DEMO_ITEMS:
            patient_id = item["patient_id"]
            fin = item["fin"]
            if patient_id is None and fin:
                row = conn.execute(
                    "SELECT patient_id FROM v_episode WHERE fin = ?", (fin,)
                ).fetchone()
                if row is None:
                    continue
                patient_id = row["patient_id"]

            cur = conn.execute(
                """
                INSERT OR IGNORE INTO queue_item (
                    demo_key, kind, severity, title, summary,
                    source_type, source_id, patient_id, fin,
                    priority, assigned_role, status, org_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', '260001')
                """,
                (
                    item["demo_key"],
                    item["kind"],
                    item["severity"],
                    item["title"],
                    item["summary"],
                    item["source_type"],
                    item["source_id"],
                    patient_id,
                    fin,
                    item["priority"],
                    item["assigned_role"],
                ),
            )
            inserted += cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return inserted


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Seed demo triage queue items")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    n = seed_queue_demo(args.db)
    print(f"Seeded {n} new demo queue item(s) into {args.db}")
