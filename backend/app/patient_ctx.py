"""Shared plumbing for the patient companion-app routers.

Three jobs:

1. **Episode context** — resolve the authenticated patient to their anchor
   episode, current phase, and enrollment row. Every patient route needs this,
   so it lives here rather than being re-queried per router.

2. **Write fan-out** — every patient action writes its own feature table AND
   mirrors into app.signal_event (the dashboard's one ordered stream, D6) plus
   app.audit_event (security-foundations §4: every write leaves a trail).
   Centralising this is what keeps the data contract honest.

3. **Derived numbers** — adherence percentages and milestone evidence, shared
   by the patient timeline and the dashboard summary so both surfaces report
   identical figures.

All dates come from the as-of clock (backend/app/clock.py). "Today" for a
patient is the resolved as-of date, not the wall clock — otherwise check-ins in
the frozen demo would land outside the episode window.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from .catalog import EXPECTED_DAILY_EXERCISES
from .clock import get_as_of
from .phases import EPISODE_WINDOW_DAYS, milestone_template, resolve_phase

ANTICOAGULANT_TOKENS = (
    "apixaban", "eliquis", "enoxaparin", "lovenox", "warfarin", "coumadin",
    "rivaroxaban", "xarelto", "dabigatran", "heparin", "aspirin 81",
)
ANALGESIC_TOKENS = (
    "oxycodone", "hydrocodone", "acetaminophen", "tylenol", "tramadol",
    "ibuprofen", "naproxen", "celecoxib", "morphine", "gabapentin",
)


def now_iso() -> str:
    """Real wall-clock time. Use for audit rows — when the action truly happened."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def event_iso(ctx: Dict[str, Any]) -> str:
    """Timestamp for a patient-generated clinical event.

    Uses the as-of DATE with the real time-of-day: on the frozen demo clock a
    check-in submitted "today" must land inside the episode window, or the
    dashboard timeline would show it months after discharge. Keeping the real
    time-of-day preserves ordering between several events on the same day.

    Audit rows deliberately keep now_iso() — an audit trail records when
    something actually happened, not when the demo pretends it did.
    """
    clock = datetime.now(timezone.utc).strftime("%H:%M:%S")
    return f"{ctx['as_of'].isoformat()}T{clock}+00:00"


def parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    return date.fromisoformat(value[:10])


def classify_med(name: str) -> str:
    """Bucket a discharge med name into anticoagulant | analgesic | other.

    The cohort's med names are free text with brand names in parentheses and a
    dozen spellings of the same drug (e.g. 12 variants of enoxaparin), so this
    is substring matching rather than an RxNorm lookup.
    """
    n = (name or "").lower()
    if any(tok in n for tok in ANTICOAGULANT_TOKENS):
        return "anticoagulant"
    if any(tok in n for tok in ANALGESIC_TOKENS):
        return "analgesic"
    return "other"


def procedure_type(procedure_summary: Optional[str], ms_drg: Optional[str]) -> str:
    """hip | femur | other, from the ICD-10-PCS procedure text.

    The cohort splits cleanly: 'Replacement of ... hip joint' vs femoral/femur
    fixation. DRG alone can't distinguish (480–482 covers both).
    """
    text = (procedure_summary or "").lower()
    if "hip joint" in text or "hip replacement" in text:
        return "hip"
    if "femur" in text or "femoral" in text:
        return "femur"
    if "hip" in text:
        return "hip"
    return "other"


# ---------------------------------------------------------------------------
# Episode context
# ---------------------------------------------------------------------------


def load_context(conn, patient: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve the caller's episode, phase, and enrollment.

    Raises 404 if the anchor FIN no longer resolves (e.g. a stale identifier
    after a cohort reload).
    """
    as_of, as_of_mode = get_as_of()
    fin = patient["fin"]

    row = conn.execute(
        """
        SELECT v.patient_id, v.mrn, v.patient_name, v.birth_date, v.sex, v.fin,
               v.admit_date, v.discharge_date, v.admit_datetime, v.discharge_datetime,
               v.window_end, v.ms_drg, v.procedure_summary, v.procedure_date,
               v.discharge_disposition, v.discharge_disposition_code,
               v.principal_diagnosis, v.length_of_stay_days,
               e.attending_name, e.hospital_service,
               p.phone_mobile, p.phone_home,
               p.emergency_contact_name, p.emergency_contact_relationship,
               p.emergency_contact_phone
        FROM v_episode v
        JOIN encounter e ON e.fin = v.fin
        JOIN patient p ON p.patient_id = v.patient_id
        WHERE v.fin = ?
        """,
        (fin,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Episode FIN {fin} not found")

    discharge = parse_date(row["discharge_date"])
    admit = parse_date(row["admit_date"])
    phase = resolve_phase(
        admit_date=admit,
        discharge_date=discharge,
        disposition_code=row["discharge_disposition_code"],
        disposition=row["discharge_disposition"],
        as_of=as_of,
    )

    enrollment = conn.execute(
        "SELECT * FROM app.patient_enrollment WHERE fin = ?", (fin,)
    ).fetchone()

    window_end = parse_date(row["window_end"])
    days_remaining = max(0, (window_end - as_of).days) if window_end else None

    return {
        "as_of": as_of,
        "as_of_mode": as_of_mode,
        "patient_id": row["patient_id"],
        "fin": fin,
        "org_id": patient["org_id"],
        "actor_id": patient["id"],
        "actor_role": patient.get("role", "patient"),
        "episode": dict(row),
        "phase": phase["phase"],
        "phase_detail": phase,
        "enrollment": dict(enrollment) if enrollment else None,
        "discharge_date": discharge,
        "window_end": window_end,
        "days_remaining": days_remaining,
    }


def require_enrollment(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """409 when a feature is used before onboarding completes."""
    if not ctx.get("enrollment"):
        raise HTTPException(
            status_code=409,
            detail="Not enrolled yet — complete onboarding first (POST /api/patient/enrollment)",
        )
    return ctx["enrollment"]


def submitted_by(ctx: Dict[str, Any]) -> str:
    enrollment = ctx.get("enrollment") or {}
    return enrollment.get("relationship") or "self"


# ---------------------------------------------------------------------------
# Write fan-out
# ---------------------------------------------------------------------------


def write_signal(
    conn,
    ctx: Dict[str, Any],
    *,
    kind: str,
    severity: str = "green",
    detail: Optional[Dict[str, Any]] = None,
    occurred_at: Optional[str] = None,
) -> int:
    """Append to app.signal_event — the stream the dashboard timeline reads."""
    cur = conn.execute(
        """
        INSERT INTO app.signal_event (
            patient_id, fin, occurred_at, kind, severity, detail_json, org_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ctx["patient_id"],
            ctx["fin"],
            occurred_at or event_iso(ctx),
            kind,
            severity,
            json.dumps(detail or {}),
            ctx["org_id"],
        ),
    )
    return int(cur.lastrowid)


def write_audit(
    conn,
    ctx: Dict[str, Any],
    *,
    action: str,
    entity_type: str,
    entity_id: Optional[str],
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    conn.execute(
        """
        INSERT INTO app.audit_event (
            actor_id, actor_role, action, entity_type, entity_id,
            patient_id, org_id, detail_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ctx["actor_id"],
            ctx["actor_role"],
            action,
            entity_type,
            entity_id,
            ctx["patient_id"],
            ctx["org_id"],
            json.dumps(detail or {}),
        ),
    )


def enqueue(
    conn,
    ctx: Dict[str, Any],
    *,
    kind: str,
    severity: str,
    title: str,
    summary: Optional[str],
    priority: int,
    assigned_role: str,
    source_type: Optional[str] = None,
    source_id: Optional[str] = None,
    signal_event_id: Optional[int] = None,
) -> int:
    """Create a provider triage alert.

    Uses the existing app.queue_item shape and kinds, so alerts render in the
    dashboard's TriageQueue with no changes on that side.
    """
    cur = conn.execute(
        """
        INSERT INTO app.queue_item (
            kind, severity, title, summary, source_type, source_id,
            signal_event_id, patient_id, fin, priority, assigned_role,
            status, created_at, org_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
        """,
        (
            kind,
            severity,
            title,
            summary,
            source_type,
            source_id,
            signal_event_id,
            ctx["patient_id"],
            ctx["fin"],
            priority,
            assigned_role,
            now_iso(),
            ctx["org_id"],
        ),
    )
    return int(cur.lastrowid)


# ---------------------------------------------------------------------------
# Derived numbers
# ---------------------------------------------------------------------------


def _eligible_days(ctx: Dict[str, Any]) -> int:
    """Days the patient could plausibly have engaged, discharge → as-of."""
    discharge = ctx["discharge_date"]
    if not discharge:
        return 0
    span = (ctx["as_of"] - discharge).days + 1
    return max(0, min(span, EPISODE_WINDOW_DAYS + 1))


def checkin_adherence(conn, ctx: Dict[str, Any]) -> Dict[str, Any]:
    expected = _eligible_days(ctx)
    done = conn.execute(
        "SELECT COUNT(DISTINCT checkin_date) FROM app.daily_checkin WHERE fin = ?",
        (ctx["fin"],),
    ).fetchone()[0]
    return {
        "days_completed": done,
        "days_expected": expected,
        "pct": round(100 * done / expected) if expected else None,
    }


def pt_adherence(conn, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Day-based PT adherence: days with at least one logged exercise."""
    expected_daily = EXPECTED_DAILY_EXERCISES.get(ctx["phase"], 3)
    expected_days = _eligible_days(ctx)
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT log_date) AS days, COUNT(*) AS sessions
        FROM app.pt_exercise_log
        WHERE fin = ? AND completed = 1
        """,
        (ctx["fin"],),
    ).fetchone()
    days = row["days"] or 0
    return {
        "days_logged": days,
        "days_expected": expected_days,
        "sessions_logged": row["sessions"] or 0,
        "expected_daily_exercises": expected_daily,
        "pct": round(100 * days / expected_days) if expected_days else None,
    }


def med_adherence(conn, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Taken / (taken + missed), overall and for anticoagulants alone."""
    rows = conn.execute(
        """
        SELECT s.med_class, d.status, COUNT(*) AS n
        FROM app.med_dose_event d
        JOIN app.med_schedule s ON s.id = d.med_schedule_id
        WHERE d.fin = ?
        GROUP BY s.med_class, d.status
        """,
        (ctx["fin"],),
    ).fetchall()

    def pct(taken: int, missed: int) -> Optional[int]:
        total = taken + missed
        return round(100 * taken / total) if total else None

    overall = {"taken": 0, "missed": 0, "skipped": 0}
    anticoag = {"taken": 0, "missed": 0, "skipped": 0}
    for r in rows:
        status = r["status"]
        if status in overall:
            overall[status] += r["n"]
            if r["med_class"] == "anticoagulant":
                anticoag[status] += r["n"]

    return {
        "taken": overall["taken"],
        "missed": overall["missed"],
        "skipped": overall["skipped"],
        "pct": pct(overall["taken"], overall["missed"]),
        "anticoagulant_taken": anticoag["taken"],
        "anticoagulant_missed": anticoag["missed"],
        "anticoagulant_pct": pct(anticoag["taken"], anticoag["missed"]),
    }


def has_anticoagulant(conn, fin: str) -> bool:
    rows = conn.execute(
        """
        SELECT COALESCE(name_display, name) AS name
        FROM medication WHERE fin = ? AND context = 'discharge'
        """,
        (fin,),
    ).fetchall()
    return any(classify_med(r["name"]) == "anticoagulant" for r in rows)


# ---------------------------------------------------------------------------
# Milestones
# ---------------------------------------------------------------------------


def ensure_milestones(conn, ctx: Dict[str, Any]) -> None:
    """Create this episode's milestone rows if they don't exist yet."""
    existing = conn.execute(
        "SELECT COUNT(*) FROM app.episode_milestone WHERE fin = ?", (ctx["fin"],)
    ).fetchone()[0]
    if existing:
        return

    discharge = ctx["discharge_date"]
    template = milestone_template(
        disposition_code=ctx["episode"]["discharge_disposition_code"],
        disposition=ctx["episode"]["discharge_disposition"],
        has_anticoagulant=has_anticoagulant(conn, ctx["fin"]),
    )
    for m in template:
        target = (
            (discharge + timedelta(days=m["offset"])).isoformat() if discharge else None
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO app.episode_milestone (
                patient_id, fin, code, phase, label, target_date,
                status, sort_order, source, org_id
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, 'derived', ?)
            """,
            (
                ctx["patient_id"],
                ctx["fin"],
                m["code"],
                m["phase"],
                m["label"],
                target,
                m["sort_order"],
                ctx["org_id"],
            ),
        )


def _gather_evidence(conn, ctx: Dict[str, Any]) -> Dict[str, bool]:
    """Which milestone evidence conditions currently hold."""
    fin = ctx["fin"]
    ev: Dict[str, bool] = {}

    checkins = conn.execute(
        """
        SELECT checkin_date, pain_score, mobility_status
        FROM app.daily_checkin WHERE fin = ? ORDER BY checkin_date DESC
        """,
        (fin,),
    ).fetchall()
    ev["checkin_any"] = len(checkins) > 0

    mobility_seen = {c["mobility_status"] for c in checkins if c["mobility_status"]}
    ev["mobility_walker"] = bool(
        mobility_seen & {"walker", "cane", "independent"}
    )
    ev["mobility_cane"] = bool(mobility_seen & {"cane", "independent"})
    ev["mobility_independent"] = "independent" in mobility_seen

    recent_pain = [c["pain_score"] for c in checkins[:3] if c["pain_score"] is not None]
    ev["pain_under_4"] = bool(recent_pain) and (sum(recent_pain) / len(recent_pain)) < 4

    pt = pt_adherence(conn, ctx)
    ev["pt_any"] = pt["sessions_logged"] > 0
    ev["pt_adherence_50"] = (pt["pct"] or 0) >= 50

    taken_days = conn.execute(
        """
        SELECT COUNT(DISTINCT d.due_date) FROM app.med_dose_event d
        JOIN app.med_schedule s ON s.id = d.med_schedule_id
        WHERE d.fin = ? AND d.status = 'taken' AND s.med_class = 'anticoagulant'
        """,
        (fin,),
    ).fetchone()[0]
    ev["med_streak_5"] = taken_days >= 5

    for code in ("home_safety", "snf_discharge_readiness"):
        total_critical = conn.execute(
            "SELECT COUNT(*) FROM app.checklist_item WHERE checklist_code = ? AND critical = 1",
            (code,),
        ).fetchone()[0]
        answered_critical = conn.execute(
            """
            SELECT COUNT(*) FROM app.checklist_response r
            JOIN app.checklist_item i
              ON i.checklist_code = r.checklist_code AND i.item_code = r.item_code
            WHERE r.fin = ? AND r.checklist_code = ? AND i.critical = 1
              AND r.answer IN ('yes', 'na')
            """,
            (fin, code),
        ).fetchone()[0]
        ev[f"checklist_{code}"] = total_critical > 0 and answered_critical >= total_critical

    for kind in ("pcp", "surgeon"):
        attended = conn.execute(
            "SELECT COUNT(*) FROM app.appointment WHERE fin = ? AND kind = ? AND attended = 1",
            (fin, kind),
        ).fetchone()[0]
        ev[f"appointment_{kind}"] = attended > 0

    ev["window_end"] = bool(ctx["window_end"] and ctx["as_of"] >= ctx["window_end"])
    return ev


# evidence key per milestone code (mirrors phases.py templates)
_EVIDENCE_BY_CODE = {
    "first_checkin": "checkin_any",
    "pt_started": "pt_any",
    "snf_therapy_started": "pt_any",
    "med_routine": "med_streak_5",
    "home_safety_done": "checklist_home_safety",
    "snf_discharge_ready": "checklist_snf_discharge_readiness",
    "pcp_visit": "appointment_pcp",
    "surgeon_followup": "appointment_surgeon",
    "walker_steady": "mobility_walker",
    "walker_to_cane": "mobility_cane",
    "independent_adl": "mobility_independent",
    "pt_halfway": "pt_adherence_50",
    "pain_controlled": "pain_under_4",
    "episode_complete": "window_end",
}


def refresh_milestones(conn, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Re-evaluate milestone status from current evidence; return the rows.

    Called after every patient write so the provider and patient views agree.
    A met milestone never reverts — recovery progress is monotonic, and
    un-meeting one would read as a regression the patient didn't cause.
    """
    ensure_milestones(conn, ctx)
    evidence = _gather_evidence(conn, ctx)
    as_of = ctx["as_of"]

    rows = conn.execute(
        "SELECT * FROM app.episode_milestone WHERE fin = ? ORDER BY sort_order",
        (ctx["fin"],),
    ).fetchall()

    out: List[Dict[str, Any]] = []
    for r in rows:
        status = r["status"]
        met_at = r["met_at"]
        if status != "met":
            key = _EVIDENCE_BY_CODE.get(r["code"])
            if key and evidence.get(key):
                status, met_at = "met", event_iso(ctx)
            else:
                target = parse_date(r["target_date"])
                status = "missed" if target and as_of > target else "pending"
        if status != r["status"] or met_at != r["met_at"]:
            conn.execute(
                "UPDATE app.episode_milestone SET status = ?, met_at = ? WHERE id = ?",
                (status, met_at, r["id"]),
            )
        item = dict(r)
        item["status"] = status
        item["met_at"] = met_at
        out.append(item)
    return out
