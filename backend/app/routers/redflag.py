"""Patient app: red-flag symptom triage (A3 severity routing).

  GET  /api/patient/redflags/questions — structured intake definitions
  GET  /api/patient/redflags           — this episode's reports
  POST /api/patient/redflags           — submit a report, get guidance

Six categories, each with structured questions: fever, calf pain/swelling
(DVT), chest pain/SOB (PE), wound drainage/redness, uncontrolled pain, falls.
Scoring and guidance live in backend/app/rules.py.

A positive answer does two things, per the A3 contract:
  (a) returns in-app guidance telling the patient what to do and how fast, and
  (b) writes a high-priority app.queue_item so the navigator sees it — the same
      table and `app_symptom` kind the dashboard triage queue already renders.

Education and routing only, never diagnosis (core-functionality.md §E).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import get_current_patient
from ..db import get_connection
from ..patient_ctx import (
    enqueue,
    event_iso,
    load_context,
    now_iso,
    require_enrollment,
    submitted_by,
    write_audit,
    write_signal,
)
from ..rules import CATEGORIES, GUIDANCE, QUEUE_PRIORITY, evaluate, queue_title

router = APIRouter(prefix="/api/patient", tags=["patient"])


class ReportBody(BaseModel):
    category: str
    answers: Dict[str, Any] = {}


class ReportOut(BaseModel):
    id: int
    category: str
    title: str
    severity: str
    guidance_code: Optional[str]
    reasons: List[str]
    reported_at: str
    reported_by: Optional[str]
    queue_item_id: Optional[int]


class SubmitResponse(BaseModel):
    report: ReportOut
    guidance: Dict[str, str]
    care_team_notified: bool
    emergency_contact: Optional[Dict[str, Optional[str]]]


@router.get("/redflags/questions")
def get_questions(
    patient: Dict[str, Any] = Depends(get_current_patient),
) -> Dict[str, Any]:
    """Intake definitions plus the guidance copy, so the app can render offline
    of the scoring logic."""
    conn = get_connection()
    try:
        ctx = load_context(conn, patient)
    finally:
        conn.close()
    return {
        "meta": {"as_of": ctx["as_of"].isoformat(), "fin": ctx["fin"]},
        "categories": CATEGORIES,
        "guidance": GUIDANCE,
    }


@router.get("/redflags", response_model=List[ReportOut])
def list_reports(
    patient: Dict[str, Any] = Depends(get_current_patient),
) -> List[ReportOut]:
    conn = get_connection()
    try:
        ctx = load_context(conn, patient)
        rows = conn.execute(
            """
            SELECT * FROM app.red_flag_report WHERE fin = ?
            ORDER BY reported_at DESC LIMIT 50
            """,
            (ctx["fin"],),
        ).fetchall()
    finally:
        conn.close()

    out: List[ReportOut] = []
    for r in rows:
        answers = json.loads(r["answers_json"] or "{}")
        out.append(
            ReportOut(
                id=r["id"],
                category=r["category"],
                title=answers.get("_title") or r["category"],
                severity=r["severity"],
                guidance_code=r["guidance_code"],
                reasons=answers.get("_reasons") or [],
                reported_at=r["reported_at"],
                reported_by=r["reported_by"],
                queue_item_id=r["queue_item_id"],
            )
        )
    return out


@router.post("/redflags", response_model=SubmitResponse)
def submit_report(
    body: ReportBody, patient: Dict[str, Any] = Depends(get_current_patient)
) -> SubmitResponse:
    try:
        verdict = evaluate(body.category, body.answers)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    severity = verdict["severity"]
    conn = get_connection()
    try:
        ctx = load_context(conn, patient)
        require_enrollment(ctx)
        by = submitted_by(ctx)

        # Store the raw answers plus the evaluated summary, so a provider can
        # see exactly what was asked and answered.
        answers_payload = dict(body.answers)
        answers_payload["_title"] = verdict["title"]
        answers_payload["_reasons"] = verdict["reasons"]

        signal_id = write_signal(
            conn,
            ctx,
            kind="symptom",
            severity=severity,
            detail={
                "category": body.category,
                "title": verdict["title"],
                "reasons": verdict["reasons"],
                "guidance_code": verdict["guidance_code"],
            },
        )

        queue_item_id: Optional[int] = None
        if severity in ("red", "yellow"):
            queue_item_id = enqueue(
                conn,
                ctx,
                kind="app_symptom",
                severity=severity,
                title=queue_title(body.category, severity, verdict["reasons"]),
                summary=(
                    "; ".join(verdict["reasons"])
                    + f" · app guidance: {verdict['guidance_code']}"
                ),
                priority=QUEUE_PRIORITY.get(severity, 25),
                assigned_role="Ortho navigator",
                source_type="signal_event",
                source_id=str(signal_id),
                signal_event_id=signal_id,
            )

        cur = conn.execute(
            """
            INSERT INTO app.red_flag_report (
                patient_id, fin, category, severity, answers_json,
                guidance_code, reported_at, reported_by,
                signal_event_id, queue_item_id, org_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ctx["patient_id"],
                ctx["fin"],
                body.category,
                severity,
                json.dumps(answers_payload),
                verdict["guidance_code"],
                event_iso(ctx),
                by,
                signal_id,
                queue_item_id,
                ctx["org_id"],
            ),
        )
        report_id = int(cur.lastrowid)

        write_audit(
            conn,
            ctx,
            action="redflag.submit",
            entity_type="red_flag_report",
            entity_id=str(report_id),
            detail={
                "category": body.category,
                "severity": severity,
                "guidance_code": verdict["guidance_code"],
                "queue_item_id": queue_item_id,
            },
        )
        conn.commit()

        row = conn.execute(
            "SELECT * FROM app.red_flag_report WHERE id = ?", (report_id,)
        ).fetchone()
        ep = ctx["episode"]
        emergency_contact = {
            "name": ep["emergency_contact_name"],
            "relationship": ep["emergency_contact_relationship"],
            "phone": ep["emergency_contact_phone"],
        }
    finally:
        conn.close()

    return SubmitResponse(
        report=ReportOut(
            id=row["id"],
            category=row["category"],
            title=verdict["title"],
            severity=row["severity"],
            guidance_code=row["guidance_code"],
            reasons=verdict["reasons"],
            reported_at=row["reported_at"],
            reported_by=row["reported_by"],
            queue_item_id=row["queue_item_id"],
        ),
        guidance=verdict["guidance"],
        care_team_notified=queue_item_id is not None,
        # Shown alongside emergency guidance so the patient has someone to call.
        emergency_contact=emergency_contact if severity == "red" else None,
    )
