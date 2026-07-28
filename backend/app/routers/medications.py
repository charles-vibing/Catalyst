"""Patient app: medication tracker (A4), anticoagulation-first.

  GET  /api/patient/medications            — schedule + today's doses + adherence
  POST /api/patient/medications/dose       — record taken / missed / skipped
  GET  /api/patient/medications/adherence  — rollup + per-day history

The schedule is derived once from the cohort's discharge medication list
(main.medication where context='discharge') into app.med_schedule, classifying
each drug as anticoagulant | analgesic | other. Anticoagulation is the clinical
priority after hip fracture surgery — a missed Eliquis/Lovenox/warfarin dose is
what the navigator most wants to see — so a missed anticoagulant dose raises a
provider alert while other misses ride the timeline.

Reminders are in-app only for the MVP: reminder_time is stored and surfaced as
"due now" in the UI, but nothing sends a push or SMS (TODO.md).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import get_current_patient
from ..db import get_connection
from ..patient_ctx import (
    classify_med,
    enqueue,
    event_iso,
    load_context,
    med_adherence,
    now_iso,
    refresh_milestones,
    require_enrollment,
    write_audit,
    write_signal,
)

router = APIRouter(prefix="/api/patient", tags=["patient"])

DOSE_STATUSES = ["taken", "missed", "skipped"]

# Default in-app reminder slots by doses/day.
REMINDER_TIMES = {1: ["09:00"], 2: ["09:00", "21:00"], 3: ["08:00", "14:00", "20:00"], 4: ["08:00", "12:00", "16:00", "20:00"]}


def _frequency_per_day(sig: Optional[str], frequency: Optional[str]) -> int:
    """Parse doses/day out of free-text sig / frequency.

    The cohort writes these as prose ("Take 1 tablet by mouth twice daily"), so
    this is keyword matching with a conservative default of once daily.
    """
    text = f"{sig or ''} {frequency or ''}".lower()
    if re.search(r"\b(four times|qid|q6h)\b", text):
        return 4
    if re.search(r"\b(three times|tid|q8h)\b", text):
        return 3
    if re.search(r"\b(twice|bid|q12h)\b", text):
        return 2
    if re.search(r"\b(every 4 hours|q4h)\b", text):
        return 4
    if re.search(r"\b(as needed|prn)\b", text):
        return 1
    return 1


class MedOut(BaseModel):
    id: int
    name_display: str
    med_class: str
    sig: Optional[str]
    frequency_per_day: int
    reminder_time: Optional[str]
    indication: Optional[str] = None
    doses_today: List[Dict[str, Any]]


class MedListResponse(BaseModel):
    meta: Dict[str, Any]
    medications: List[MedOut]
    adherence: Dict[str, Any]
    anticoagulant_names: List[str]


class DoseBody(BaseModel):
    med_schedule_id: int
    status: str
    dose_index: int = 0
    due_date: Optional[str] = None
    note: Optional[str] = None


class DoseResponse(BaseModel):
    recorded: Dict[str, Any]
    adherence: Dict[str, Any]
    acknowledgement: str
    alerts: List[Dict[str, Any]]
    milestones_met: List[str]


def ensure_schedule(conn, ctx: Dict[str, Any]) -> None:
    """Materialise app.med_schedule from the cohort discharge med list once."""
    existing = conn.execute(
        "SELECT COUNT(*) FROM app.med_schedule WHERE fin = ?", (ctx["fin"],)
    ).fetchone()[0]
    if existing:
        return

    rows = conn.execute(
        """
        SELECT id, COALESCE(name_display, name) AS name, rxnorm, sig, frequency, indication
        FROM medication
        WHERE fin = ? AND context = 'discharge'
        ORDER BY name
        """,
        (ctx["fin"],),
    ).fetchall()

    for r in rows:
        med_class = classify_med(r["name"])
        per_day = _frequency_per_day(r["sig"], r["frequency"])
        slots = REMINDER_TIMES.get(per_day, ["09:00"])
        conn.execute(
            """
            INSERT OR IGNORE INTO app.med_schedule (
                patient_id, fin, medication_id, name_display, med_class,
                rxnorm, sig, frequency_per_day, reminder_time, active, org_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                ctx["patient_id"],
                ctx["fin"],
                r["id"],
                r["name"],
                med_class,
                r["rxnorm"],
                r["sig"],
                per_day,
                slots[0],
                ctx["org_id"],
            ),
        )


@router.get("/medications", response_model=MedListResponse)
def list_medications(
    patient: Dict[str, Any] = Depends(get_current_patient),
) -> MedListResponse:
    conn = get_connection()
    try:
        ctx = load_context(conn, patient)
        require_enrollment(ctx)
        ensure_schedule(conn, ctx)
        conn.commit()

        today = ctx["as_of"].isoformat()
        rows = conn.execute(
            """
            SELECT s.*, m.indication
            FROM app.med_schedule s
            LEFT JOIN medication m ON m.id = s.medication_id
            WHERE s.fin = ? AND s.active = 1
            ORDER BY CASE s.med_class
                       WHEN 'anticoagulant' THEN 0
                       WHEN 'analgesic' THEN 1
                       ELSE 2 END,
                     s.name_display
            """,
            (ctx["fin"],),
        ).fetchall()

        doses = conn.execute(
            """
            SELECT med_schedule_id, dose_index, status, recorded_at
            FROM app.med_dose_event WHERE fin = ? AND due_date = ?
            """,
            (ctx["fin"], today),
        ).fetchall()
        by_med: Dict[int, Dict[int, Dict[str, Any]]] = {}
        for d in doses:
            by_med.setdefault(d["med_schedule_id"], {})[d["dose_index"]] = {
                "status": d["status"],
                "recorded_at": d["recorded_at"],
            }

        adherence = med_adherence(conn, ctx)
    finally:
        conn.close()

    meds: List[MedOut] = []
    for r in rows:
        per_day = r["frequency_per_day"] or 1
        slots = REMINDER_TIMES.get(per_day, ["09:00"])
        recorded = by_med.get(r["id"], {})
        doses_today = [
            {
                "dose_index": i,
                "reminder_time": slots[i] if i < len(slots) else None,
                "status": recorded.get(i, {}).get("status"),
                "recorded_at": recorded.get(i, {}).get("recorded_at"),
            }
            for i in range(per_day)
        ]
        meds.append(
            MedOut(
                id=r["id"],
                name_display=r["name_display"],
                med_class=r["med_class"],
                sig=r["sig"],
                frequency_per_day=per_day,
                reminder_time=r["reminder_time"],
                indication=r["indication"],
                doses_today=doses_today,
            )
        )

    return MedListResponse(
        meta={
            "as_of": ctx["as_of"].isoformat(),
            "as_of_mode": ctx["as_of_mode"],
            "fin": ctx["fin"],
            "reminders": "in_app_only",
        },
        medications=meds,
        adherence=adherence,
        anticoagulant_names=[
            m.name_display for m in meds if m.med_class == "anticoagulant"
        ],
    )


@router.post("/medications/dose", response_model=DoseResponse)
def record_dose(
    body: DoseBody, patient: Dict[str, Any] = Depends(get_current_patient)
) -> DoseResponse:
    if body.status not in DOSE_STATUSES:
        raise HTTPException(
            status_code=400, detail=f"status must be one of {DOSE_STATUSES}"
        )

    conn = get_connection()
    try:
        ctx = load_context(conn, patient)
        require_enrollment(ctx)
        ensure_schedule(conn, ctx)

        med = conn.execute(
            "SELECT * FROM app.med_schedule WHERE id = ? AND fin = ?",
            (body.med_schedule_id, ctx["fin"]),
        ).fetchone()
        if med is None:
            raise HTTPException(status_code=404, detail="Medication not on your schedule")

        due_date = body.due_date or ctx["as_of"].isoformat()
        if body.dose_index < 0 or body.dose_index >= (med["frequency_per_day"] or 1):
            raise HTTPException(
                status_code=400,
                detail=f"dose_index out of range for {med['frequency_per_day']} dose(s)/day",
            )

        conn.execute(
            """
            INSERT INTO app.med_dose_event (
                patient_id, fin, med_schedule_id, due_date, dose_index,
                status, recorded_at, note, org_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(med_schedule_id, due_date, dose_index) DO UPDATE SET
                status = excluded.status,
                recorded_at = excluded.recorded_at,
                note = excluded.note
            """,
            (
                ctx["patient_id"],
                ctx["fin"],
                body.med_schedule_id,
                due_date,
                body.dose_index,
                body.status,
                event_iso(ctx),
                body.note,
                ctx["org_id"],
            ),
        )

        is_anticoag = med["med_class"] == "anticoagulant"
        kind = "med_taken" if body.status == "taken" else "med_missed"
        if body.status == "taken":
            severity = "green"
        elif is_anticoag:
            severity = "red" if body.status == "missed" else "yellow"
        else:
            severity = "yellow"

        signal_id = write_signal(
            conn,
            ctx,
            kind=kind,
            severity=severity,
            detail={
                "medication": med["name_display"],
                "med_class": med["med_class"],
                "status": body.status,
                "due_date": due_date,
                "dose_index": body.dose_index,
            },
            occurred_at=f"{due_date}T09:00:00+00:00",
        )

        alerts: List[Dict[str, Any]] = []
        if is_anticoag and body.status == "missed":
            # Count recent anticoagulant misses — a single miss is worth a
            # yellow nudge, a pattern is worth interrupting someone.
            recent_misses = conn.execute(
                """
                SELECT COUNT(*) FROM app.med_dose_event d
                JOIN app.med_schedule s ON s.id = d.med_schedule_id
                WHERE d.fin = ? AND s.med_class = 'anticoagulant'
                  AND d.status = 'missed' AND d.due_date >= date(?, '-7 days')
                """,
                (ctx["fin"], due_date),
            ).fetchone()[0]
            qid = enqueue(
                conn,
                ctx,
                kind="app_symptom",
                severity="red" if recent_misses >= 2 else "yellow",
                title=f"Missed anticoagulant: {med['name_display'][:40]}",
                summary=(
                    f"{recent_misses} missed dose(s) in the last 7 days · "
                    "DVT/PE prophylaxis at risk"
                ),
                priority=5 if recent_misses >= 2 else 25,
                assigned_role="Ortho navigator",
                source_type="signal_event",
                source_id=str(signal_id),
                signal_event_id=signal_id,
            )
            alerts.append(
                {
                    "queue_item_id": qid,
                    "reason": "missed_anticoagulant",
                    "recent_misses": recent_misses,
                }
            )

        write_audit(
            conn,
            ctx,
            action="medication.dose",
            entity_type="med_dose_event",
            entity_id=f"{body.med_schedule_id}:{due_date}:{body.dose_index}",
            detail={
                "status": body.status,
                "med_class": med["med_class"],
                "medication": med["name_display"],
            },
        )

        before = {
            m["code"] for m in conn.execute(
                "SELECT code FROM app.episode_milestone WHERE fin = ? AND status = 'met'",
                (ctx["fin"],),
            ).fetchall()
        }
        milestones = refresh_milestones(conn, ctx)
        newly_met = [
            m["label"] for m in milestones
            if m["status"] == "met" and m["code"] not in before
        ]
        conn.commit()
        adherence = med_adherence(conn, ctx)
    finally:
        conn.close()

    if body.status == "taken":
        ack = "Logged — thanks."
    elif is_anticoag:
        ack = (
            "Logged. Blood thinners protect against clots, so your care team "
            "will follow up. Take your next dose at the usual time — don't "
            "double up."
        )
    else:
        ack = "Logged."

    return DoseResponse(
        recorded={
            "med_schedule_id": body.med_schedule_id,
            "medication": med["name_display"],
            "status": body.status,
            "due_date": due_date,
            "dose_index": body.dose_index,
        },
        adherence=adherence,
        acknowledgement=ack,
        alerts=alerts,
        milestones_met=newly_met,
    )


@router.get("/medications/adherence")
def get_med_adherence(
    patient: Dict[str, Any] = Depends(get_current_patient),
) -> Dict[str, Any]:
    conn = get_connection()
    try:
        ctx = load_context(conn, patient)
        require_enrollment(ctx)
        adherence = med_adherence(conn, ctx)
        by_day = conn.execute(
            """
            SELECT d.due_date,
                   SUM(CASE WHEN d.status = 'taken' THEN 1 ELSE 0 END) AS taken,
                   SUM(CASE WHEN d.status = 'missed' THEN 1 ELSE 0 END) AS missed
            FROM app.med_dose_event d
            WHERE d.fin = ?
            GROUP BY d.due_date ORDER BY d.due_date DESC LIMIT 30
            """,
            (ctx["fin"],),
        ).fetchall()
    finally:
        conn.close()
    return {
        "meta": {"as_of": ctx["as_of"].isoformat(), "fin": ctx["fin"]},
        "adherence": adherence,
        "by_day": [
            {"date": r["due_date"], "taken": r["taken"], "missed": r["missed"]}
            for r in by_day
        ],
    }
