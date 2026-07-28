#!/usr/bin/env python3
"""Seed realistic patient-app history for the demo episodes.

Three episodes, chosen so the demo exercises every phase and feature:

  p27 Okoye, Dennis   FIN 007521  PRIMARY. Discharged home 2026-06-14, DRG 481
      hip replacement, on enoxaparin (Lovenox). 14 days of check-ins, PT logs, and doses up
      to the frozen as-of date, PCP visit attended, one resolved fever scare.
      Sits in home_recovery with a believable improving trajectory.

  p25 Abernathy, Clyde FIN 007361 SNF pathway. Discharged to a skilled nursing
      facility 2026-06-02, 91 years old. Sparse facility-proxy engagement plus a
      partly-completed discharge-readiness checklist with two open blockers —
      what the SNF liaison should see.

  p29 Baptiste, Jerome FIN 007681 Early transition-home. Discharged 2026-06-23,
      on warfarin. Only 5 days of history, an unanswered home-safety checklist,
      a missed anticoagulant dose, and an open DVT red flag — the "needs
      attention today" story.

Deterministic: no randomness, no date.today(). Everything is derived from each
episode's discharge date and the as-of clock, so re-running produces the same
history. Idempotent via the natural keys on each table (upserts), so it is safe
to run repeatedly; queue items are cleared per-episode first to avoid piling up
duplicate alerts.

  python3 db/seed_patient_demo.py
  python3 db/seed_patient_demo.py --reset   # wipe this episode's app data first
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "db" / "catalyst.db"
DEFAULT_APP_DB = REPO_ROOT / "db" / "app.db"

sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.catalog import CHECKLIST_ITEMS  # noqa: E402
from app.phases import milestone_template, resolve_phase  # noqa: E402

DEMO_FINS = ["007521", "007361", "007681"]

# Tables holding per-episode patient-app state, for --reset.
EPISODE_TABLES = [
    "daily_checkin",
    "pt_exercise_log",
    "med_dose_event",
    "med_schedule",
    "red_flag_report",
    "appointment",
    "checklist_response",
    "episode_milestone",
    "patient_enrollment",
    "signal_event",
    "referral_status_event",
]


def _connect(db_path: Path, app_db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(app_db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("ATTACH DATABASE ? AS cohort", (str(db_path),))
    return conn


def _as_of(conn: sqlite3.Connection) -> date:
    row = conn.execute(
        "SELECT value FROM app_setting WHERE key = 'as_of_date'"
    ).fetchone()
    return date.fromisoformat(row["value"]) if row and row["value"] else date(2026, 6, 28)


def _classify_med(name: str) -> str:
    n = (name or "").lower()
    if any(t in n for t in ("apixaban", "eliquis", "enoxaparin", "lovenox", "warfarin", "coumadin")):
        return "anticoagulant"
    if any(t in n for t in ("oxycodone", "acetaminophen", "tylenol", "tramadol", "ibuprofen")):
        return "analgesic"
    return "other"


def _episode(conn: sqlite3.Connection, fin: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        """
        SELECT v.*, e.attending_name, e.hospital_service
        FROM cohort.v_episode v
        JOIN cohort.encounter e ON e.fin = v.fin
        WHERE v.fin = ?
        """,
        (fin,),
    ).fetchone()


def _ts(day: date, hhmm: str) -> str:
    return f"{day.isoformat()}T{hhmm}:00+00:00"


def _signal(
    conn: sqlite3.Connection,
    ep: sqlite3.Row,
    when: str,
    kind: str,
    severity: str,
    detail: Dict[str, Any],
) -> int:
    cur = conn.execute(
        """
        INSERT INTO signal_event (
            patient_id, fin, occurred_at, kind, severity, detail_json, org_id
        ) VALUES (?, ?, ?, ?, ?, ?, '260001')
        """,
        (ep["patient_id"], ep["fin"], when, kind, severity, json.dumps(detail)),
    )
    return int(cur.lastrowid)


def _audit(conn: sqlite3.Connection, ep: sqlite3.Row, action: str, entity: str, eid: str) -> None:
    conn.execute(
        """
        INSERT INTO audit_event (
            actor_id, actor_role, action, entity_type, entity_id,
            patient_id, org_id, detail_json
        ) VALUES (?, 'patient', ?, ?, ?, ?, '260001', '{"seeded": true}')
        """,
        (f"patient-{ep['patient_id']}", action, entity, eid, ep["patient_id"]),
    )


# ---------------------------------------------------------------------------
# Trajectory: what a recovering hip-fracture patient's numbers look like
# ---------------------------------------------------------------------------


def _trajectory(day_index: int, total_days: int, *, frail: bool = False) -> Dict[str, Any]:
    """Pain / mood / sleep / mobility for a given day after discharge.

    Improving but not monotonic — pain ticks up on the day of a longer walk, and
    frail patients progress more slowly and stall at the walker.
    """
    pain = max(2, 7 - (day_index * 0.28 if not frail else day_index * 0.15))
    if day_index in (4, 11):  # post-therapy flare
        pain += 1.5
    pain = int(min(9, round(pain)))

    if frail:
        mobility = "bed" if day_index < 2 else ("chair" if day_index < 6 else "walker")
    elif day_index < 2:
        mobility = "chair"
    elif day_index < 9:
        mobility = "walker"
    elif day_index < 20:
        mobility = "walker" if day_index % 4 else "cane"
    else:
        mobility = "cane" if day_index < 26 else "independent"

    mood = "low" if pain >= 7 else ("ok" if pain >= 5 else "good")
    sleep = "poor" if pain >= 7 else ("fair" if pain >= 4 else "good")
    return {
        "pain_score": pain,
        "mood": mood,
        "sleep_quality": sleep,
        "mobility_status": mobility,
        "weight_bearing_status": "as_instructed",
        "pt_completed": day_index % 5 != 3,  # skips roughly one day in five
    }


def _exercises_for_phase(conn: sqlite3.Connection, phase: str) -> List[sqlite3.Row]:
    sets = {
        "snf": ["snf"],
        "irf": ["snf"],
        "transition_home": ["snf", "transition_home"],
        "home_recovery": ["transition_home", "home_recovery"],
    }.get(phase, ["transition_home"])
    ph = ",".join("?" for _ in sets)
    return conn.execute(
        f"SELECT * FROM pt_exercise WHERE phase IN ({ph}) ORDER BY sort_order", sets
    ).fetchall()


# ---------------------------------------------------------------------------
# Per-episode seeding
# ---------------------------------------------------------------------------


def seed_episode(
    conn: sqlite3.Connection,
    fin: str,
    as_of: date,
    *,
    relationship: str,
    frail: bool,
    engagement: float,
    story: str,
) -> Dict[str, int]:
    """Seed one episode. `engagement` is the fraction of days checked in."""
    ep = _episode(conn, fin)
    if ep is None:
        return {"skipped": 1}

    discharge = date.fromisoformat(ep["discharge_date"])
    days_elapsed = (as_of - discharge).days
    if days_elapsed < 0:
        return {"skipped": 1}
    counts = {"checkins": 0, "pt_logs": 0, "doses": 0, "flags": 0, "messages": 0}

    phase_now = resolve_phase(
        admit_date=date.fromisoformat(ep["admit_date"]),
        discharge_date=discharge,
        disposition_code=ep["discharge_disposition_code"],
        disposition=ep["discharge_disposition"],
        as_of=as_of,
    )

    # --- enrollment -------------------------------------------------------
    proc = (ep["procedure_summary"] or "").lower()
    proc_type = "hip" if "hip joint" in proc else ("femur" if "femur" in proc or "femoral" in proc else "other")
    conn.execute(
        """
        INSERT INTO patient_enrollment (
            patient_id, fin, relationship, confirmed_procedure_type,
            confirmed_procedure_text, confirmed_surgeon,
            confirmed_discharge_destination, disposition_code, contact_phone,
            enrolled_at, status, org_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, 'active', '260001')
        ON CONFLICT(fin) DO UPDATE SET relationship = excluded.relationship
        """,
        (
            ep["patient_id"],
            fin,
            relationship,
            proc_type,
            ep["procedure_summary"],
            ep["attending_name"],
            ep["discharge_disposition"],
            ep["discharge_disposition_code"],
            _ts(discharge + timedelta(days=1), "10:15"),
        ),
    )
    _signal(
        conn,
        ep,
        _ts(discharge + timedelta(days=1), "10:15"),
        "checkin_done",
        "green",
        {"event": "enrolled", "relationship": relationship},
    )

    # --- milestones -------------------------------------------------------
    has_anticoag = any(
        _classify_med(r["name"]) == "anticoagulant"
        for r in conn.execute(
            "SELECT COALESCE(name_display, name) AS name FROM cohort.medication "
            "WHERE fin = ? AND context = 'discharge'",
            (fin,),
        ).fetchall()
    )
    for m in milestone_template(
        disposition_code=ep["discharge_disposition_code"],
        disposition=ep["discharge_disposition"],
        has_anticoagulant=has_anticoag,
    ):
        conn.execute(
            """
            INSERT OR IGNORE INTO episode_milestone (
                patient_id, fin, code, phase, label, target_date, status,
                sort_order, source, org_id
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, 'derived', '260001')
            """,
            (
                ep["patient_id"],
                fin,
                m["code"],
                m["phase"],
                m["label"],
                (discharge + timedelta(days=m["offset"])).isoformat(),
                m["sort_order"],
            ),
        )

    # --- medication schedule ---------------------------------------------
    for r in conn.execute(
        """
        SELECT id, COALESCE(name_display, name) AS name, rxnorm, sig, frequency
        FROM cohort.medication WHERE fin = ? AND context = 'discharge' ORDER BY name
        """,
        (fin,),
    ).fetchall():
        text = f"{r['sig'] or ''} {r['frequency'] or ''}".lower()
        per_day = 2 if ("twice" in text or "bid" in text) else 1
        conn.execute(
            """
            INSERT OR IGNORE INTO med_schedule (
                patient_id, fin, medication_id, name_display, med_class, rxnorm,
                sig, frequency_per_day, reminder_time, active, org_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, '260001')
            """,
            (
                ep["patient_id"],
                fin,
                r["id"],
                r["name"],
                _classify_med(r["name"]),
                r["rxnorm"],
                r["sig"],
                per_day,
                "09:00" if per_day == 1 else "09:00",
            ),
        )
    meds = conn.execute(
        "SELECT * FROM med_schedule WHERE fin = ? AND active = 1", (fin,)
    ).fetchall()

    # --- appointments -----------------------------------------------------
    for r in conn.execute(
        "SELECT id, type, referred_to, appointment_datetime FROM cohort.referral WHERE fin = ?",
        (fin,),
    ).fetchall():
        rtype = (r["type"] or "").lower()
        kind = "pcp" if "primary care" in rtype else ("home_health" if "home health" in rtype else None)
        if not kind:
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO appointment (
                patient_id, fin, kind, title, provider_name, scheduled_at,
                source, referral_id, confirmed, org_id
            ) VALUES (?, ?, ?, ?, ?, ?, 'referral', ?, 1, '260001')
            """,
            (
                ep["patient_id"],
                fin,
                kind,
                "Primary care follow-up" if kind == "pcp" else "Home health visit",
                r["referred_to"],
                r["appointment_datetime"],
                r["id"],
            ),
        )
    for kind, offset, title, provider in (
        ("surgeon", 14, "Surgeon follow-up", ep["attending_name"]),
        ("pt", 3, "Physical therapy", "Memorial General Rehabilitation"),
    ):
        conn.execute(
            """
            INSERT OR IGNORE INTO appointment (
                patient_id, fin, kind, title, provider_name, scheduled_at,
                location, source, confirmed, org_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'seeded', 1, '260001')
            """,
            (
                ep["patient_id"],
                fin,
                kind,
                title,
                provider,
                _ts(discharge + timedelta(days=offset), "10:00"),
                "Memorial General Orthopedic Clinic" if kind == "surgeon" else None,
            ),
        )

    # Mark past appointments attended (the PCP one also updates referral status).
    for appt in conn.execute(
        "SELECT * FROM appointment WHERE fin = ? AND scheduled_at IS NOT NULL", (fin,)
    ).fetchall():
        sched = date.fromisoformat(appt["scheduled_at"][:10])
        if sched >= as_of:
            continue
        attended = not (story == "needs_attention" and appt["kind"] == "pcp")
        conn.execute(
            "UPDATE appointment SET attended = ?, attended_at = ? WHERE id = ?",
            (int(attended), _ts(sched, "11:30"), appt["id"]),
        )
        if appt["kind"] == "pcp":
            conn.execute(
                """
                INSERT INTO referral_status_event (
                    patient_id, fin, referral_id, status, noted_at, noted_by, note, org_id
                ) VALUES (?, ?, ?, ?, ?, ?, 'Reported in patient app', '260001')
                """,
                (
                    ep["patient_id"],
                    fin,
                    appt["referral_id"],
                    "completed" if attended else "no_show",
                    _ts(sched, "11:30"),
                    f"patient-{ep['patient_id']}",
                ),
            )
        _signal(
            conn,
            ep,
            _ts(sched, "11:30"),
            "checkin_done" if attended else "help_request",
            "green" if attended else "yellow",
            {
                "event": "appointment_attendance",
                "kind": appt["kind"],
                "title": appt["title"],
                "attended": attended,
            },
        )

    # --- daily loop: check-ins, PT, doses ---------------------------------
    for i in range(days_elapsed + 1):
        day = discharge + timedelta(days=i)
        # Engagement gaps: skip some days entirely, deterministically.
        if i > 0 and (i * 7 % 10) / 10.0 >= engagement:
            _signal(conn, ep, _ts(day, "23:00"), "checkin_missed", "yellow", {"day_index": i})
            continue

        t = _trajectory(i, days_elapsed, frail=frail)
        conn.execute(
            """
            INSERT INTO daily_checkin (
                patient_id, fin, checkin_date, pain_score, mood, sleep_quality,
                mobility_status, weight_bearing_status, pt_completed, note,
                submitted_at, submitted_by, org_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '260001')
            ON CONFLICT(fin, checkin_date) DO UPDATE SET
                pain_score = excluded.pain_score,
                mood = excluded.mood,
                sleep_quality = excluded.sleep_quality,
                mobility_status = excluded.mobility_status,
                pt_completed = excluded.pt_completed
            """,
            (
                ep["patient_id"],
                fin,
                day.isoformat(),
                t["pain_score"],
                t["mood"],
                t["sleep_quality"],
                t["mobility_status"],
                t["weight_bearing_status"],
                int(t["pt_completed"]),
                None,
                _ts(day, "08:40"),
                relationship,
            ),
        )
        counts["checkins"] += 1
        severity = "red" if t["pain_score"] >= 8 else ("yellow" if t["pain_score"] >= 6 else "green")
        _signal(
            conn,
            ep,
            _ts(day, "08:40"),
            "checkin_done",
            severity,
            {
                "pain_score": t["pain_score"],
                "mood": t["mood"],
                "sleep_quality": t["sleep_quality"],
                "mobility_status": t["mobility_status"],
                "weight_bearing_status": t["weight_bearing_status"],
                "pt_completed": t["pt_completed"],
                "concerns": [f"Pain {t['pain_score']}/10"] if severity != "green" else [],
            },
        )

        # PT logs on days the patient reported doing exercises.
        if t["pt_completed"]:
            phase_that_day = resolve_phase(
                admit_date=date.fromisoformat(ep["admit_date"]),
                discharge_date=discharge,
                disposition_code=ep["discharge_disposition_code"],
                disposition=ep["discharge_disposition"],
                as_of=day,
            )["phase"]
            for ex in _exercises_for_phase(conn, phase_that_day)[:3]:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO pt_exercise_log (
                        patient_id, fin, exercise_code, log_date, sets_done,
                        reps_done, completed, difficulty, logged_at, org_id
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, '260001')
                    """,
                    (
                        ep["patient_id"],
                        fin,
                        ex["code"],
                        day.isoformat(),
                        ex["default_sets"],
                        ex["default_reps"],
                        "hard" if t["pain_score"] >= 6 else "ok",
                        _ts(day, "16:20"),
                    ),
                )
                counts["pt_logs"] += 1

        # Doses. The "needs attention" story misses anticoagulant doses late.
        for med in meds:
            for dose_index in range(med["frequency_per_day"] or 1):
                miss = (
                    story == "needs_attention"
                    and med["med_class"] == "anticoagulant"
                    and i >= days_elapsed - 2
                ) or (i > 0 and (i * 3 + dose_index) % 11 == 0)
                status = "missed" if miss else "taken"
                conn.execute(
                    """
                    INSERT INTO med_dose_event (
                        patient_id, fin, med_schedule_id, due_date, dose_index,
                        status, recorded_at, org_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, '260001')
                    ON CONFLICT(med_schedule_id, due_date, dose_index)
                    DO UPDATE SET status = excluded.status
                    """,
                    (
                        ep["patient_id"],
                        fin,
                        med["id"],
                        day.isoformat(),
                        dose_index,
                        status,
                        _ts(day, "09:05"),
                    ),
                )
                counts["doses"] += 1
                _signal(
                    conn,
                    ep,
                    _ts(day, "09:05"),
                    "med_taken" if status == "taken" else "med_missed",
                    "green"
                    if status == "taken"
                    else ("red" if med["med_class"] == "anticoagulant" else "yellow"),
                    {
                        "medication": med["name_display"],
                        "med_class": med["med_class"],
                        "status": status,
                        "due_date": day.isoformat(),
                        "dose_index": dose_index,
                    },
                )

    # --- checklists -------------------------------------------------------
    if story == "snf":
        # Partly complete, two critical blockers open — the liaison's problem.
        # Both are CRITICAL items, so they surface as blockers to the liaison.
        blocked = {"walk_50ft", "understands_wb"}
        answered_day = discharge + timedelta(days=10)
        for item in [c for c in CHECKLIST_ITEMS if c["checklist_code"] == "snf_discharge_readiness"]:
            if item["item_code"] in ("transport_ready", "appointments_known"):
                continue  # left unanswered
            answer = "no" if item["item_code"] in blocked else "yes"
            conn.execute(
                """
                INSERT INTO checklist_response (
                    patient_id, fin, checklist_code, item_code, answer, note,
                    answered_at, answered_by, org_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '260001')
                ON CONFLICT(fin, checklist_code, item_code) DO UPDATE SET answer = excluded.answer
                """,
                (
                    ep["patient_id"],
                    fin,
                    "snf_discharge_readiness",
                    item["item_code"],
                    answer,
                    {
                        "walk_50ft": "Managing about 25 feet — tires quickly",
                        "understands_wb": "Confused about how much weight is allowed",
                    }.get(item["item_code"]),
                    _ts(answered_day, "14:00"),
                    relationship,
                ),
            )
    elif story == "on_track":
        answered_day = discharge + timedelta(days=4)
        for item in [c for c in CHECKLIST_ITEMS if c["checklist_code"] == "home_safety"]:
            conn.execute(
                """
                INSERT INTO checklist_response (
                    patient_id, fin, checklist_code, item_code, answer, note,
                    answered_at, answered_by, org_id
                ) VALUES (?, ?, ?, ?, 'yes', NULL, ?, ?, '260001')
                ON CONFLICT(fin, checklist_code, item_code) DO UPDATE SET answer = excluded.answer
                """,
                (
                    ep["patient_id"],
                    fin,
                    "home_safety",
                    item["item_code"],
                    _ts(answered_day, "19:30"),
                    relationship,
                ),
            )

    # --- red flags --------------------------------------------------------
    if story == "on_track":
        # A fever scare early on, already handled — shows a resolved red flag.
        flag_day = discharge + timedelta(days=5)
        sid = _signal(
            conn,
            ep,
            _ts(flag_day, "20:10"),
            "symptom",
            "yellow",
            {
                "category": "fever",
                "title": "Fever or chills",
                "reasons": ["Temperature 100.6°F (100.4–100.9)"],
                "guidance_code": "call_care_team_today",
            },
        )
        qcur = conn.execute(
            """
            INSERT INTO queue_item (
                kind, severity, title, summary, source_type, source_id,
                signal_event_id, patient_id, fin, priority, assigned_role,
                status, resolution_action, resolution_note, created_at,
                resolved_at, org_id
            ) VALUES ('app_symptom', 'yellow', ?, ?, 'signal_event', ?, ?, ?, ?, 25,
                      'Ortho navigator', 'resolved', 'call_patient', ?, ?, ?, '260001')
            """,
            (
                "Symptom watch: Temperature 100.6°F (100.4–100.9)",
                "Low-grade fever day 5 · app guidance: call_care_team_today",
                str(sid),
                sid,
                ep["patient_id"],
                fin,
                "Called patient — incision clean, no drainage. Advised fluids and recheck.",
                _ts(flag_day, "20:10"),
                _ts(flag_day + timedelta(days=1), "09:20"),
            ),
        )
        conn.execute(
            """
            INSERT INTO red_flag_report (
                patient_id, fin, category, severity, answers_json, guidance_code,
                reported_at, reported_by, signal_event_id, queue_item_id, org_id
            ) VALUES (?, ?, 'fever', 'yellow', ?, 'call_care_team_today', ?, ?, ?, ?, '260001')
            """,
            (
                ep["patient_id"],
                fin,
                json.dumps(
                    {
                        "temp_f": 100.6,
                        "chills": True,
                        "confusion": False,
                        "_title": "Fever or chills",
                        "_reasons": ["Temperature 100.6°F (100.4–100.9)"],
                    }
                ),
                _ts(flag_day, "20:10"),
                relationship,
                sid,
                int(qcur.lastrowid),
            ),
        )
        counts["flags"] += 1

    elif story == "needs_attention":
        # Open DVT concern from yesterday — the reason to look at this patient.
        flag_day = as_of - timedelta(days=1)
        sid = _signal(
            conn,
            ep,
            _ts(flag_day, "18:45"),
            "symptom",
            "red",
            {
                "category": "dvt",
                "title": "Calf pain or swelling",
                "reasons": ["One-sided calf findings — needs same-day assessment"],
                "guidance_code": "call_surgeon_now",
            },
        )
        qcur = conn.execute(
            """
            INSERT INTO queue_item (
                kind, severity, title, summary, source_type, source_id,
                signal_event_id, patient_id, fin, priority, assigned_role,
                status, created_at, org_id
            ) VALUES ('app_symptom', 'red', ?, ?, 'signal_event', ?, ?, ?, ?, 5,
                      'Ortho navigator', 'open', ?, '260001')
            """,
            (
                "Red flag: One-sided calf findings — needs same-day assessment",
                "Right calf pain + swelling, warm · on warfarin · app guidance: call_surgeon_now",
                str(sid),
                sid,
                ep["patient_id"],
                fin,
                _ts(flag_day, "18:45"),
            ),
        )
        conn.execute(
            """
            INSERT INTO red_flag_report (
                patient_id, fin, category, severity, answers_json, guidance_code,
                reported_at, reported_by, signal_event_id, queue_item_id, org_id
            ) VALUES (?, ?, 'dvt', 'red', ?, 'call_surgeon_now', ?, ?, ?, ?, '260001')
            """,
            (
                ep["patient_id"],
                fin,
                json.dumps(
                    {
                        "one_sided": True,
                        "calf_pain": True,
                        "swelling": True,
                        "warm_red": True,
                        "_title": "Calf pain or swelling",
                        "_reasons": ["One-sided calf findings — needs same-day assessment"],
                    }
                ),
                _ts(flag_day, "18:45"),
                relationship,
                sid,
                int(qcur.lastrowid),
            ),
        )
        counts["flags"] += 1

    # --- a message thread -------------------------------------------------
    thread_specs = {
        "on_track": (
            "Question about driving",
            [
                ("patient", "When can I start driving again? I'm off the strong pain pills now."),
                (
                    "care_team",
                    "Good question — usually once you're off opioid pain medication and can "
                    "brake without hesitating, which is often around 4 weeks. Dr. Mitchell "
                    "will confirm at your follow-up.",
                ),
            ],
        ),
        "needs_attention": (
            "My leg is swollen",
            [
                ("patient", "My right calf is sore and looks bigger than the left one. Should I worry?"),
            ],
        ),
        "snf": (
            "Getting home",
            [
                ("caregiver", "Dad wants to come home. What has to happen first?"),
                (
                    "care_team",
                    "He's close. The team wants him walking 50 feet with the walker and a plan "
                    "for daytime help. Let's talk Thursday.",
                ),
            ],
        ),
    }
    subject, msgs = thread_specs[story]
    thread_day = as_of - timedelta(days=2)
    tcur = conn.execute(
        """
        INSERT INTO message_thread (
            patient_id, fin, subject, status, created_at, last_message_at,
            unread_provider, unread_patient, org_id
        ) VALUES (?, ?, ?, 'open', ?, ?, ?, ?, '260001')
        """,
        (
            ep["patient_id"],
            fin,
            subject,
            _ts(thread_day, "13:00"),
            _ts(thread_day + timedelta(days=1), "09:00"),
            1 if msgs[-1][0] != "care_team" else 0,
            1 if msgs[-1][0] == "care_team" else 0,
        ),
    )
    thread_id = int(tcur.lastrowid)
    for offset, (role, text) in enumerate(msgs):
        conn.execute(
            """
            INSERT INTO message (thread_id, sender_role, sender_name, body, sent_at, org_id)
            VALUES (?, ?, ?, ?, ?, '260001')
            """,
            (
                thread_id,
                role,
                ep["patient_name"] if role != "care_team" else "Memorial General care team",
                text,
                _ts(thread_day + timedelta(days=offset), "13:00" if offset == 0 else "09:00"),
            ),
        )
        counts["messages"] += 1
    _audit(conn, ep, "message.send", "message", str(thread_id))
    _audit(conn, ep, "enrollment.confirm", "patient_enrollment", fin)

    return counts


def _reset_episode(conn: sqlite3.Connection, fin: str) -> None:
    for table in EPISODE_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE fin = ?", (fin,))
    conn.execute(
        "DELETE FROM message WHERE thread_id IN (SELECT id FROM message_thread WHERE fin = ?)",
        (fin,),
    )
    conn.execute("DELETE FROM message_thread WHERE fin = ?", (fin,))
    # Only clear app-generated alerts; seeded dashboard demo rows have demo_key.
    conn.execute(
        "DELETE FROM queue_item WHERE fin = ? AND kind LIKE 'app_%' AND demo_key IS NULL",
        (fin,),
    )


def seed_patient_demo(
    db_path: Path = DEFAULT_DB, app_db_path: Path = DEFAULT_APP_DB, reset: bool = False
) -> Dict[str, Dict[str, int]]:
    conn = _connect(db_path, app_db_path)
    results: Dict[str, Dict[str, int]] = {}
    try:
        as_of = _as_of(conn)
        specs = [
            ("007521", {"relationship": "self", "frail": False, "engagement": 0.85, "story": "on_track"}),
            ("007361", {"relationship": "caregiver", "frail": True, "engagement": 0.4, "story": "snf"}),
            ("007681", {"relationship": "self", "frail": False, "engagement": 0.8, "story": "needs_attention"}),
        ]
        for fin, spec in specs:
            if reset:
                _reset_episode(conn, fin)
            results[fin] = seed_episode(conn, fin, as_of, **spec)
        conn.commit()
    finally:
        conn.close()
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed patient-app demo history")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--app-db", type=Path, default=DEFAULT_APP_DB)
    parser.add_argument(
        "--reset", action="store_true", help="clear existing app data for the demo episodes first"
    )
    args = parser.parse_args()
    out = seed_patient_demo(args.db, args.app_db, reset=args.reset)
    for fin, counts in out.items():
        detail = ", ".join(f"{k}={v}" for k, v in counts.items())
        print(f"  {fin}: {detail}")
    print(f"Seeded patient-app demo history into {args.app_db}")
