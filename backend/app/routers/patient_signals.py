"""Dashboard-side reads of patient-app data (completes D6, D7 inbox, A8 provider side).

  GET  /api/episodes/{fin}/signals          — unified patient signal timeline (D6)
  GET  /api/episodes/{fin}/patient-summary  — enrollment + adherence + checklists
  GET  /api/messages                        — care-team message inbox
  POST /api/messages/{thread_id}/reply      — care team replies to a patient
  POST /api/messages/{thread_id}/close      — close a thread

D6 (live signal timeline) was specified in the dashboard MVP plan but never
built, because there was no patient app generating signals. Now there is, so
this is the provider surface those writes land on.

All routes use the staff auth stub (Depends(get_current_user)) and are org-scoped.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..auth import get_current_user
from ..catalog import CHECKLIST_META
from ..clock import get_as_of
from ..db import get_connection
from ..patient_ctx import now_iso

router = APIRouter(prefix="/api", tags=["patient-data"])

# Human labels for signal kinds, so the dashboard doesn't restate the vocabulary.
SIGNAL_LABELS = {
    "checkin_done": "Check-in",
    "checkin_missed": "Missed check-in",
    "symptom": "Symptom report",
    "med_taken": "Medication taken",
    "med_missed": "Medication missed",
    "help_request": "Help request",
}


class SignalOut(BaseModel):
    id: int
    occurred_at: str
    kind: str
    label: str
    severity: Optional[str]
    detail: Dict[str, Any]
    headline: str


class SignalsResponse(BaseModel):
    meta: Dict[str, Any]
    signals: List[SignalOut]
    counts: Dict[str, int]


class PatientSummaryResponse(BaseModel):
    meta: Dict[str, Any]
    enrolled: bool
    enrollment: Optional[Dict[str, Any]]
    phase: Optional[str]
    phase_label: Optional[str]
    milestones: List[Dict[str, Any]]
    adherence: Dict[str, Any]
    latest_checkin: Optional[Dict[str, Any]]
    checkin_trend: List[Dict[str, Any]]
    red_flags: List[Dict[str, Any]]
    checklists: List[Dict[str, Any]]
    open_alerts: int


class ThreadSummary(BaseModel):
    id: int
    patient_id: int
    patient_name: Optional[str]
    fin: str
    subject: str
    status: str
    last_message_at: Optional[str]
    unread_provider: int
    message_count: int
    last_preview: Optional[str]
    messages: List[Dict[str, Any]]


class InboxResponse(BaseModel):
    meta: Dict[str, Any]
    threads: List[ThreadSummary]


class ReplyBody(BaseModel):
    body: str = Field(min_length=1)
    sender_name: Optional[str] = None


def _headline(kind: str, severity: Optional[str], detail: Dict[str, Any]) -> str:
    """One-line provider-readable summary of a signal."""
    if kind == "symptom":
        reasons = detail.get("reasons") or []
        base = detail.get("title") or "Symptom"
        return f"{base}: {reasons[0]}" if reasons else base
    if kind in ("med_taken", "med_missed"):
        med = detail.get("medication") or "medication"
        verb = "took" if kind == "med_taken" else "missed"
        cls = detail.get("med_class")
        suffix = " (anticoagulant)" if cls == "anticoagulant" else ""
        return f"Patient {verb} {med}{suffix}"
    if kind == "help_request":
        if detail.get("event") == "appointment_attendance":
            return f"Did not attend {detail.get('title', 'appointment')}"
        return f"Help request: {detail.get('preview', '')}"[:120]

    event = detail.get("event")
    if event == "pt_logged":
        name = detail.get("exercise_name", "exercise")
        diff = detail.get("difficulty")
        return f"Logged PT: {name}" + (f" ({diff})" if diff else "")
    if event == "checklist_saved":
        code = detail.get("checklist_code", "checklist")
        title = CHECKLIST_META.get(code, {}).get("title", code)
        blockers = detail.get("blockers") or []
        return f"{title}: {detail.get('answered')}/{detail.get('total')} answered" + (
            f", {len(blockers)} gap(s)" if blockers else ""
        )
    if event == "message_sent":
        return f"Message: {detail.get('preview', '')}"[:120]
    if event == "enrolled":
        return f"Enrolled in the patient app ({detail.get('relationship', 'self')})"
    if event == "appointment_attendance":
        return f"Attended {detail.get('title', 'appointment')}"

    # Plain daily check-in
    bits: List[str] = []
    if detail.get("pain_score") is not None:
        bits.append(f"pain {detail['pain_score']}/10")
    if detail.get("mobility_status"):
        bits.append(str(detail["mobility_status"]))
    if detail.get("pt_completed") is not None:
        bits.append("PT done" if detail["pt_completed"] else "PT not done")
    concerns = detail.get("concerns") or []
    if concerns:
        bits.append("· " + "; ".join(concerns))
    return "Check-in: " + (", ".join(bits) if bits else "submitted")


@router.get("/episodes/{fin}/signals", response_model=SignalsResponse)
def get_signals(
    fin: str,
    limit: int = Query(default=200, ge=1, le=500),
    user: Dict[str, str] = Depends(get_current_user),
) -> SignalsResponse:
    """Unified patient signal timeline for one episode (D6)."""
    as_of, mode = get_as_of()
    conn = get_connection()
    try:
        episode = conn.execute(
            "SELECT patient_id, patient_name FROM v_episode WHERE fin = ?", (fin,)
        ).fetchone()
        if episode is None:
            raise HTTPException(status_code=404, detail=f"Episode FIN {fin} not found")

        rows = conn.execute(
            """
            SELECT id, occurred_at, kind, severity, detail_json
            FROM app.signal_event
            WHERE fin = ? AND org_id = ?
            ORDER BY occurred_at DESC, id DESC
            LIMIT ?
            """,
            (fin, user["org_id"], limit),
        ).fetchall()
    finally:
        conn.close()

    signals: List[SignalOut] = []
    counts: Dict[str, int] = {}
    for r in rows:
        detail = json.loads(r["detail_json"] or "{}")
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
        if r["severity"]:
            counts[r["severity"]] = counts.get(r["severity"], 0) + 1
        signals.append(
            SignalOut(
                id=r["id"],
                occurred_at=r["occurred_at"],
                kind=r["kind"],
                label=SIGNAL_LABELS.get(r["kind"], r["kind"]),
                severity=r["severity"],
                detail=detail,
                headline=_headline(r["kind"], r["severity"], detail),
            )
        )

    return SignalsResponse(
        meta={
            "as_of": as_of.isoformat(),
            "as_of_mode": mode,
            "org_id": user["org_id"],
            "fin": fin,
            "patient_id": episode["patient_id"],
            "patient_name": episode["patient_name"],
            "total": len(signals),
        },
        signals=signals,
        counts=counts,
    )


@router.get("/episodes/{fin}/patient-summary", response_model=PatientSummaryResponse)
def get_patient_summary(
    fin: str, user: Dict[str, str] = Depends(get_current_user)
) -> PatientSummaryResponse:
    """Engagement rollup for the episode detail panel.

    Reuses the same helpers the patient timeline uses, so the adherence numbers
    a navigator sees are identical to the ones the patient sees.
    """
    from ..patient_ctx import (
        checkin_adherence,
        load_context,
        med_adherence,
        pt_adherence,
        refresh_milestones,
    )

    conn = get_connection()
    try:
        episode = conn.execute(
            "SELECT patient_id, patient_name FROM v_episode WHERE fin = ?", (fin,)
        ).fetchone()
        if episode is None:
            raise HTTPException(status_code=404, detail=f"Episode FIN {fin} not found")

        # Borrow the patient context loader with a synthetic staff-side identity.
        ctx = load_context(
            conn,
            {
                "id": user["id"],
                "role": user.get("role", "ortho_navigator"),
                "org_id": user["org_id"],
                "fin": fin,
            },
        )

        enrollment = ctx["enrollment"]

        # Re-evaluate milestone status from current evidence before reading it.
        # The patient timeline does the same on every load, so without this the
        # provider would see stale "pending" rows for goals the patient has
        # already met — e.g. after a seeded history, or after the as-of clock
        # moves. Idempotent, so a GET stays safe to repeat.
        if enrollment:
            refresh_milestones(conn, ctx)
            conn.commit()
        milestones = conn.execute(
            """
            SELECT code, phase, label, target_date, status, met_at
            FROM app.episode_milestone WHERE fin = ? ORDER BY sort_order
            """,
            (fin,),
        ).fetchall()

        latest = conn.execute(
            """
            SELECT * FROM app.daily_checkin WHERE fin = ?
            ORDER BY checkin_date DESC LIMIT 1
            """,
            (fin,),
        ).fetchone()

        trend = conn.execute(
            """
            SELECT checkin_date, pain_score, mobility_status, pt_completed,
                   weight_bearing_status, mood
            FROM app.daily_checkin WHERE fin = ?
            ORDER BY checkin_date DESC LIMIT 14
            """,
            (fin,),
        ).fetchall()

        flags = conn.execute(
            """
            SELECT id, category, severity, guidance_code, reported_at,
                   answers_json, queue_item_id
            FROM app.red_flag_report WHERE fin = ?
            ORDER BY reported_at DESC LIMIT 20
            """,
            (fin,),
        ).fetchall()

        checklists = []
        for code, meta in CHECKLIST_META.items():
            rows = conn.execute(
                """
                SELECT i.item_code, i.label, i.critical, r.answer, r.note, r.answered_at
                FROM app.checklist_item i
                LEFT JOIN app.checklist_response r
                  ON r.checklist_code = i.checklist_code
                 AND r.item_code = i.item_code AND r.fin = ?
                WHERE i.checklist_code = ?
                ORDER BY i.sort_order
                """,
                (fin, code),
            ).fetchall()
            answered = [r for r in rows if r["answer"]]
            if not answered:
                continue
            blockers = [
                {"item_code": r["item_code"], "label": r["label"], "note": r["note"]}
                for r in rows
                if r["critical"] and r["answer"] == "no"
            ]
            checklists.append(
                {
                    "checklist_code": code,
                    "title": meta["title"],
                    "answered": len(answered),
                    "total": len(rows),
                    "blockers": blockers,
                    "last_answered_at": max(
                        (r["answered_at"] for r in answered if r["answered_at"]),
                        default=None,
                    ),
                }
            )

        open_alerts = conn.execute(
            """
            SELECT COUNT(*) FROM app.queue_item
            WHERE fin = ? AND status IN ('open', 'in_progress')
              AND kind LIKE 'app_%'
            """,
            (fin,),
        ).fetchone()[0]

        adherence = {
            "checkin": checkin_adherence(conn, ctx),
            "pt": pt_adherence(conn, ctx),
            "medication": med_adherence(conn, ctx),
        }
    finally:
        conn.close()

    return PatientSummaryResponse(
        meta={
            "as_of": ctx["as_of"].isoformat(),
            "as_of_mode": ctx["as_of_mode"],
            "org_id": user["org_id"],
            "fin": fin,
            "patient_name": episode["patient_name"],
        },
        enrolled=enrollment is not None,
        enrollment=enrollment,
        phase=ctx["phase"] if enrollment else None,
        phase_label=ctx["phase_detail"]["phase_label"] if enrollment else None,
        milestones=[dict(m) for m in milestones],
        adherence=adherence,
        latest_checkin=dict(latest) if latest else None,
        checkin_trend=[dict(t) for t in trend],
        red_flags=[
            {
                "id": f["id"],
                "category": f["category"],
                "severity": f["severity"],
                "guidance_code": f["guidance_code"],
                "reported_at": f["reported_at"],
                "reasons": (json.loads(f["answers_json"] or "{}")).get("_reasons", []),
                "queue_item_id": f["queue_item_id"],
            }
            for f in flags
        ],
        checklists=checklists,
        open_alerts=open_alerts,
    )


# ---------------------------------------------------------------------------
# Care-team messaging (provider side)
# ---------------------------------------------------------------------------


@router.get("/messages", response_model=InboxResponse)
def list_inbox(
    status: str = Query(default="open", description="open | closed | all"),
    fin: Optional[str] = None,
    user: Dict[str, str] = Depends(get_current_user),
) -> InboxResponse:
    as_of, mode = get_as_of()
    clauses = ["t.org_id = ?"]
    params: List[Any] = [user["org_id"]]
    if status != "all":
        clauses.append("t.status = ?")
        params.append(status)
    if fin:
        clauses.append("t.fin = ?")
        params.append(fin)

    conn = get_connection()
    try:
        rows = conn.execute(
            f"""
            SELECT t.*, p.family_name || ', ' || p.given_name AS patient_name,
                   (SELECT COUNT(*) FROM app.message m WHERE m.thread_id = t.id) AS message_count
            FROM app.message_thread t
            LEFT JOIN patient p ON p.patient_id = t.patient_id
            WHERE {' AND '.join(clauses)}
            ORDER BY t.unread_provider DESC,
                     COALESCE(t.last_message_at, t.created_at) DESC
            """,
            params,
        ).fetchall()

        threads: List[ThreadSummary] = []
        for t in rows:
            messages = conn.execute(
                "SELECT * FROM app.message WHERE thread_id = ? ORDER BY sent_at, id",
                (t["id"],),
            ).fetchall()
            threads.append(
                ThreadSummary(
                    id=t["id"],
                    patient_id=t["patient_id"],
                    patient_name=t["patient_name"],
                    fin=t["fin"],
                    subject=t["subject"],
                    status=t["status"],
                    last_message_at=t["last_message_at"],
                    unread_provider=t["unread_provider"],
                    message_count=t["message_count"],
                    last_preview=messages[-1]["body"][:160] if messages else None,
                    messages=[
                        {
                            "id": m["id"],
                            "sender_role": m["sender_role"],
                            "sender_name": m["sender_name"],
                            "body": m["body"],
                            "sent_at": m["sent_at"],
                            "read_at": m["read_at"],
                        }
                        for m in messages
                    ],
                )
            )
    finally:
        conn.close()

    return InboxResponse(
        meta={
            "as_of": as_of.isoformat(),
            "as_of_mode": mode,
            "org_id": user["org_id"],
            "status": status,
            "total": len(threads),
            "unread_threads": len([t for t in threads if t.unread_provider > 0]),
        },
        threads=threads,
    )


@router.post("/messages/{thread_id}/reply")
def reply_to_thread(
    thread_id: int,
    body: ReplyBody,
    user: Dict[str, str] = Depends(get_current_user),
) -> Dict[str, Any]:
    text = body.body.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Reply body is required")

    conn = get_connection()
    try:
        thread = conn.execute(
            "SELECT * FROM app.message_thread WHERE id = ? AND org_id = ?",
            (thread_id, user["org_id"]),
        ).fetchone()
        if thread is None:
            raise HTTPException(status_code=404, detail="Thread not found")

        stamp = now_iso()
        cur = conn.execute(
            """
            INSERT INTO app.message (
                thread_id, sender_role, sender_name, body, sent_at, org_id
            ) VALUES (?, 'care_team', ?, ?, ?, ?)
            """,
            (
                thread_id,
                body.sender_name or "Memorial General care team",
                text,
                stamp,
                user["org_id"],
            ),
        )
        message_id = int(cur.lastrowid)

        # Provider reply clears their unread count and raises the patient's.
        conn.execute(
            """
            UPDATE app.message_thread
            SET last_message_at = ?, unread_provider = 0,
                unread_patient = unread_patient + 1
            WHERE id = ?
            """,
            (stamp, thread_id),
        )
        conn.execute(
            """
            INSERT INTO app.audit_event (
                actor_id, actor_role, action, entity_type, entity_id,
                patient_id, org_id, detail_json
            ) VALUES (?, ?, 'message.reply', 'message', ?, ?, ?, ?)
            """,
            (
                user["id"],
                user.get("role"),
                str(message_id),
                thread["patient_id"],
                user["org_id"],
                json.dumps({"thread_id": thread_id}),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "thread_id": thread_id,
        "message_id": message_id,
        "sent_at": stamp,
        "sender_role": "care_team",
    }


@router.post("/messages/{thread_id}/close")
def close_thread(
    thread_id: int, user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, Any]:
    conn = get_connection()
    try:
        thread = conn.execute(
            "SELECT id, patient_id FROM app.message_thread WHERE id = ? AND org_id = ?",
            (thread_id, user["org_id"]),
        ).fetchone()
        if thread is None:
            raise HTTPException(status_code=404, detail="Thread not found")
        conn.execute(
            "UPDATE app.message_thread SET status = 'closed', unread_provider = 0 WHERE id = ?",
            (thread_id,),
        )
        conn.execute(
            """
            INSERT INTO app.audit_event (
                actor_id, actor_role, action, entity_type, entity_id,
                patient_id, org_id, detail_json
            ) VALUES (?, ?, 'message.close', 'message_thread', ?, ?, ?, '{}')
            """,
            (user["id"], user.get("role"), str(thread_id), thread["patient_id"], user["org_id"]),
        )
        conn.commit()
    finally:
        conn.close()
    return {"thread_id": thread_id, "status": "closed"}
