"""Patient app: daily check-in (A3).

  GET  /api/patient/checkin/today   — form definition + today's answers if any
  GET  /api/patient/checkin/history — recent check-ins for the trend strip
  POST /api/patient/checkin         — submit / re-submit today

One screen, under a minute: pain, mood, sleep, mobility, weight-bearing, PT
done. Writes app.daily_checkin (one row per episode per day, upsert) and mirrors
to app.signal_event so the dashboard timeline sees it.

A check-in is not a triage channel — red flags have their own structured intake
(routers/redflag.py). But two answers here are alarming enough to warrant a
queue item on their own: severe pain, and weight-bearing more than allowed
(which risks the fixation).
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import get_current_patient
from ..db import get_connection
from ..patient_ctx import (
    enqueue,
    event_iso,
    load_context,
    now_iso,
    refresh_milestones,
    require_enrollment,
    submitted_by,
    write_audit,
    write_signal,
)

router = APIRouter(prefix="/api/patient", tags=["patient"])

MOOD_OPTIONS = ["good", "ok", "low", "anxious"]
SLEEP_OPTIONS = ["good", "fair", "poor"]
MOBILITY_OPTIONS = ["bed", "chair", "walker", "cane", "independent"]
WEIGHT_BEARING_OPTIONS = [
    "as_instructed",
    "more_than_allowed",
    "less_than_allowed",
    "unsure",
]

MOBILITY_LABELS = {
    "bed": "Mostly in bed",
    "chair": "Up to a chair",
    "walker": "Walking with a walker",
    "cane": "Walking with a cane",
    "independent": "Walking on my own",
}
WEIGHT_BEARING_LABELS = {
    "as_instructed": "As my surgeon instructed",
    "more_than_allowed": "More weight than allowed",
    "less_than_allowed": "Less weight than allowed",
    "unsure": "I'm not sure",
}

# Pain at or above this triggers a provider alert from the check-in itself.
SEVERE_PAIN = 8


class CheckinBody(BaseModel):
    pain_score: Optional[int] = Field(default=None, ge=0, le=10)
    mood: Optional[str] = None
    sleep_quality: Optional[str] = None
    mobility_status: Optional[str] = None
    weight_bearing_status: Optional[str] = None
    pt_completed: Optional[bool] = None
    note: Optional[str] = None


class CheckinOut(BaseModel):
    checkin_date: str
    pain_score: Optional[int]
    mood: Optional[str]
    sleep_quality: Optional[str]
    mobility_status: Optional[str]
    weight_bearing_status: Optional[str]
    pt_completed: Optional[bool]
    note: Optional[str]
    submitted_at: Optional[str]
    submitted_by: Optional[str]


class TodayResponse(BaseModel):
    meta: Dict[str, Any]
    already_submitted: bool
    checkin: Optional[CheckinOut]
    form: Dict[str, Any]
    streak_days: int


class SubmitResponse(BaseModel):
    checkin: CheckinOut
    acknowledgement: str
    alerts: List[Dict[str, Any]]
    superseded_alerts: List[int]
    milestones_met: List[str]


def _row_to_out(row) -> CheckinOut:
    return CheckinOut(
        checkin_date=row["checkin_date"],
        pain_score=row["pain_score"],
        mood=row["mood"],
        sleep_quality=row["sleep_quality"],
        mobility_status=row["mobility_status"],
        weight_bearing_status=row["weight_bearing_status"],
        pt_completed=bool(row["pt_completed"]) if row["pt_completed"] is not None else None,
        note=row["note"],
        submitted_at=row["submitted_at"],
        submitted_by=row["submitted_by"],
    )


def _streak(conn, fin: str, as_of_iso: str) -> int:
    """Consecutive check-in days ending today (or yesterday if today is blank)."""
    dates = [
        r["checkin_date"]
        for r in conn.execute(
            "SELECT checkin_date FROM app.daily_checkin WHERE fin = ? ORDER BY checkin_date DESC",
            (fin,),
        ).fetchall()
    ]
    if not dates:
        return 0
    from datetime import date as _date

    have = set(dates)
    cursor = _date.fromisoformat(as_of_iso)
    if cursor.isoformat() not in have:
        cursor -= timedelta(days=1)
    streak = 0
    while cursor.isoformat() in have:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _form_definition(ctx: Dict[str, Any], conn) -> Dict[str, Any]:
    """Field definitions, with the surgeon's weight-bearing order for context."""
    wb = conn.execute(
        """
        SELECT weight_bearing FROM therapy_evaluation
        WHERE fin = ? AND weight_bearing IS NOT NULL
        ORDER BY eval_date DESC LIMIT 1
        """,
        (ctx["fin"],),
    ).fetchone()
    return {
        "pain": {"type": "scale", "min": 0, "max": 10, "label": "Your pain right now"},
        "mood": {"type": "choice", "options": MOOD_OPTIONS, "label": "How are you feeling?"},
        "sleep_quality": {
            "type": "choice",
            "options": SLEEP_OPTIONS,
            "label": "How did you sleep?",
        },
        "mobility_status": {
            "type": "choice",
            "options": MOBILITY_OPTIONS,
            "labels": MOBILITY_LABELS,
            "label": "How are you getting around today?",
        },
        "weight_bearing_status": {
            "type": "choice",
            "options": WEIGHT_BEARING_OPTIONS,
            "labels": WEIGHT_BEARING_LABELS,
            "label": "How much weight are you putting on your leg?",
            "order_text": wb["weight_bearing"] if wb else None,
        },
        "pt_completed": {"type": "bool", "label": "Did you do your exercises?"},
        "note": {"type": "text", "label": "Anything else? (optional)"},
    }


@router.get("/checkin/today", response_model=TodayResponse)
def get_today(patient: Dict[str, Any] = Depends(get_current_patient)) -> TodayResponse:
    conn = get_connection()
    try:
        ctx = load_context(conn, patient)
        require_enrollment(ctx)
        today = ctx["as_of"].isoformat()
        row = conn.execute(
            "SELECT * FROM app.daily_checkin WHERE fin = ? AND checkin_date = ?",
            (ctx["fin"], today),
        ).fetchone()
        form = _form_definition(ctx, conn)
        streak = _streak(conn, ctx["fin"], today)
    finally:
        conn.close()

    return TodayResponse(
        meta={
            "as_of": today,
            "as_of_mode": ctx["as_of_mode"],
            "fin": ctx["fin"],
            "phase": ctx["phase"],
        },
        already_submitted=row is not None,
        checkin=_row_to_out(row) if row else None,
        form=form,
        streak_days=streak,
    )


@router.get("/checkin/history", response_model=List[CheckinOut])
def get_history(
    days: int = 14, patient: Dict[str, Any] = Depends(get_current_patient)
) -> List[CheckinOut]:
    if days < 1 or days > 60:
        raise HTTPException(status_code=400, detail="days must be between 1 and 60")
    conn = get_connection()
    try:
        ctx = load_context(conn, patient)
        require_enrollment(ctx)
        rows = conn.execute(
            """
            SELECT * FROM app.daily_checkin WHERE fin = ?
            ORDER BY checkin_date DESC LIMIT ?
            """,
            (ctx["fin"], days),
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_out(r) for r in rows]


@router.post("/checkin", response_model=SubmitResponse)
def submit_checkin(
    body: CheckinBody, patient: Dict[str, Any] = Depends(get_current_patient)
) -> SubmitResponse:
    for field, allowed in (
        ("mood", MOOD_OPTIONS),
        ("sleep_quality", SLEEP_OPTIONS),
        ("mobility_status", MOBILITY_OPTIONS),
        ("weight_bearing_status", WEIGHT_BEARING_OPTIONS),
    ):
        value = getattr(body, field)
        if value is not None and value not in allowed:
            raise HTTPException(
                status_code=400, detail=f"{field} must be one of {allowed}"
            )

    conn = get_connection()
    try:
        ctx = load_context(conn, patient)
        require_enrollment(ctx)
        today = ctx["as_of"].isoformat()
        by = submitted_by(ctx)

        previous = conn.execute(
            """
            SELECT id, pain_score, weight_bearing_status
            FROM app.daily_checkin WHERE fin = ? AND checkin_date = ?
            """,
            (ctx["fin"], today),
        ).fetchone()

        conn.execute(
            """
            INSERT INTO app.daily_checkin (
                patient_id, fin, checkin_date, pain_score, mood, sleep_quality,
                mobility_status, weight_bearing_status, pt_completed, note,
                submitted_at, submitted_by, org_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fin, checkin_date) DO UPDATE SET
                pain_score = excluded.pain_score,
                mood = excluded.mood,
                sleep_quality = excluded.sleep_quality,
                mobility_status = excluded.mobility_status,
                weight_bearing_status = excluded.weight_bearing_status,
                pt_completed = excluded.pt_completed,
                note = excluded.note,
                submitted_at = excluded.submitted_at,
                submitted_by = excluded.submitted_by
            """,
            (
                ctx["patient_id"],
                ctx["fin"],
                today,
                body.pain_score,
                body.mood,
                body.sleep_quality,
                body.mobility_status,
                body.weight_bearing_status,
                None if body.pt_completed is None else int(body.pt_completed),
                body.note,
                event_iso(ctx),
                by,
                ctx["org_id"],
            ),
        )

        # Severity for the dashboard timeline: pain and unsafe weight-bearing.
        severity = "green"
        concerns: List[str] = []
        if body.pain_score is not None and body.pain_score >= SEVERE_PAIN:
            severity = "red"
            concerns.append(f"Pain {body.pain_score}/10")
        elif body.pain_score is not None and body.pain_score >= 6:
            severity = "yellow"
            concerns.append(f"Pain {body.pain_score}/10")
        if body.weight_bearing_status == "more_than_allowed":
            severity = "red"
            concerns.append("Weight-bearing more than allowed")
        elif body.weight_bearing_status == "unsure" and severity == "green":
            severity = "yellow"
            concerns.append("Unsure about weight-bearing limit")
        if body.mood == "low" and severity == "green":
            severity = "yellow"
            concerns.append("Low mood")

        signal_id = write_signal(
            conn,
            ctx,
            kind="checkin_done",
            severity=severity,
            detail={
                "pain_score": body.pain_score,
                "mood": body.mood,
                "sleep_quality": body.sleep_quality,
                "mobility_status": body.mobility_status,
                "weight_bearing_status": body.weight_bearing_status,
                "pt_completed": body.pt_completed,
                "concerns": concerns,
                "resubmitted": previous is not None,
            },
            occurred_at=f"{today}T12:00:00+00:00",
        )

        # Today's check-in is an upsert, so a resubmission rewrites the row an
        # earlier alert was raised from. Retract those alerts before raising a
        # new one, or the queue keeps asserting a pain score the chart no longer
        # holds. Scoped by signal kind so red-flag intake (routers/redflag.py,
        # same queue kind but kind='symptom') is never touched.
        #
        # Two deliberate limits: only 'open' items are cleared — once a
        # navigator has picked one up it is theirs to close, not ours to
        # vanish — and this resolves rather than deletes, so the original red
        # signal_event stays on the timeline and the audit trail records the
        # retraction. The severe report is still visible history; it just stops
        # being an open action item.
        superseded: List[int] = []
        if previous is not None:
            stale = conn.execute(
                """
                SELECT q.id FROM app.queue_item q
                JOIN app.signal_event se ON se.id = q.signal_event_id
                WHERE q.fin = ?
                  AND q.kind = 'app_symptom'
                  AND q.status = 'open'
                  AND se.kind = 'checkin_done'
                  AND substr(se.occurred_at, 1, 10) = ?
                """,
                (ctx["fin"], today),
            ).fetchall()

            if stale:
                old_pain = previous["pain_score"]
                if old_pain is not None and body.pain_score is not None:
                    change = f"pain {old_pain}/10 → {body.pain_score}/10"
                else:
                    change = "answers revised"
                note = (
                    f"Superseded — patient amended today's check-in ({change}). "
                    "The original report remains on the signal timeline."
                )
                for r in stale:
                    conn.execute(
                        """
                        UPDATE app.queue_item
                           SET status = 'resolved',
                               resolution_action = 'superseded',
                               resolution_note = ?,
                               resolved_at = ?
                         WHERE id = ?
                        """,
                        (note, now_iso(), int(r["id"])),
                    )
                    superseded.append(int(r["id"]))
                write_audit(
                    conn,
                    ctx,
                    action="queue.supersede",
                    entity_type="queue_item",
                    entity_id=",".join(str(i) for i in superseded),
                    detail={
                        "reason": "checkin_amended",
                        "previous_pain_score": old_pain,
                        "new_pain_score": body.pain_score,
                        "new_severity": severity,
                    },
                )

        alerts: List[Dict[str, Any]] = []
        if severity == "red":
            qid = enqueue(
                conn,
                ctx,
                kind="app_symptom",
                severity="red",
                title=f"Check-in: {concerns[0]}",
                summary="; ".join(concerns) + " — reported in daily check-in",
                priority=5,
                assigned_role="Ortho navigator",
                source_type="signal_event",
                source_id=str(signal_id),
                signal_event_id=signal_id,
            )
            alerts.append({"queue_item_id": qid, "severity": "red", "concerns": concerns})

        write_audit(
            conn,
            ctx,
            action="checkin.submit",
            entity_type="daily_checkin",
            entity_id=f"{ctx['fin']}:{today}",
            detail={"severity": severity, "resubmitted": previous is not None},
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

        row = conn.execute(
            "SELECT * FROM app.daily_checkin WHERE fin = ? AND checkin_date = ?",
            (ctx["fin"], today),
        ).fetchone()
        streak = _streak(conn, ctx["fin"], today)
    finally:
        conn.close()

    if severity == "red":
        ack = "Thanks — we've flagged this for your care team and someone will reach out."
    elif severity == "yellow":
        ack = "Thanks for checking in. Your care team can see this."
    elif streak >= 3:
        ack = f"Checked in {streak} days running — that's exactly what helps."
    else:
        ack = "Thanks for checking in."

    return SubmitResponse(
        checkin=_row_to_out(row),
        acknowledgement=ack,
        alerts=alerts,
        superseded_alerts=superseded,
        milestones_met=newly_met,
    )
