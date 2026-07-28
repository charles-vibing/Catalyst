"""Secure messaging between patient/caregiver and care team (A5 / A8).

Patient side (Depends(get_current_patient)):
  GET  /api/patient/messages                  — threads with messages
  POST /api/patient/messages                  — new thread or reply
  POST /api/patient/messages/{id}/read        — mark care-team replies read

Provider side (Depends(get_current_user)) lives in routers/patient_signals.py
so the dashboard's reads stay together.

Simple threading: one app.message_thread per topic, app.message rows inside.
unread_provider / unread_patient are denormalised counters so either surface can
badge without scanning message bodies.

"I need help" from the patient app raises a queue item — that is the
"help_request → urgent queue item" contract in core-functionality.md §C.
"""

from __future__ import annotations

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
    require_enrollment,
    submitted_by,
    write_audit,
    write_signal,
)

router = APIRouter(prefix="/api/patient", tags=["patient"])

MAX_BODY_CHARS = 2000


class MessageOut(BaseModel):
    id: int
    sender_role: str
    sender_name: Optional[str]
    body: str
    sent_at: str
    read_at: Optional[str]


class ThreadOut(BaseModel):
    id: int
    subject: str
    status: str
    created_at: str
    last_message_at: Optional[str]
    unread_patient: int
    messages: List[MessageOut]


class ThreadListResponse(BaseModel):
    meta: Dict[str, Any]
    threads: List[ThreadOut]
    care_team: List[Dict[str, str]]


class SendBody(BaseModel):
    body: str = Field(min_length=1)
    thread_id: Optional[int] = None
    subject: Optional[str] = None
    urgent: bool = False


class SendResponse(BaseModel):
    thread_id: int
    message: MessageOut
    acknowledgement: str
    care_team_notified: bool


def _thread_out(conn, row) -> ThreadOut:
    messages = conn.execute(
        "SELECT * FROM app.message WHERE thread_id = ? ORDER BY sent_at, id",
        (row["id"],),
    ).fetchall()
    return ThreadOut(
        id=row["id"],
        subject=row["subject"],
        status=row["status"],
        created_at=row["created_at"],
        last_message_at=row["last_message_at"],
        unread_patient=row["unread_patient"],
        messages=[
            MessageOut(
                id=m["id"],
                sender_role=m["sender_role"],
                sender_name=m["sender_name"],
                body=m["body"],
                sent_at=m["sent_at"],
                read_at=m["read_at"],
            )
            for m in messages
        ],
    )


@router.get("/messages", response_model=ThreadListResponse)
def list_threads(
    patient: Dict[str, Any] = Depends(get_current_patient),
) -> ThreadListResponse:
    conn = get_connection()
    try:
        ctx = load_context(conn, patient)
        require_enrollment(ctx)
        rows = conn.execute(
            """
            SELECT * FROM app.message_thread WHERE fin = ?
            ORDER BY COALESCE(last_message_at, created_at) DESC
            """,
            (ctx["fin"],),
        ).fetchall()
        threads = [_thread_out(conn, r) for r in rows]
        # Who the patient is actually writing to.
        care_team = conn.execute(
            """
            SELECT role, name FROM care_team_member WHERE fin = ?
            ORDER BY CASE role WHEN 'Attending' THEN 0 WHEN 'Case Manager' THEN 1 ELSE 2 END
            """,
            (ctx["fin"],),
        ).fetchall()
    finally:
        conn.close()

    return ThreadListResponse(
        meta={
            "as_of": ctx["as_of"].isoformat(),
            "fin": ctx["fin"],
            "unread_total": sum(t.unread_patient for t in threads),
        },
        threads=threads,
        care_team=[{"role": c["role"], "name": c["name"]} for c in care_team],
    )


@router.post("/messages", response_model=SendResponse)
def send_message(
    body: SendBody, patient: Dict[str, Any] = Depends(get_current_patient)
) -> SendResponse:
    text = body.body.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message body is required")
    if len(text) > MAX_BODY_CHARS:
        raise HTTPException(
            status_code=400, detail=f"Message must be under {MAX_BODY_CHARS} characters"
        )

    conn = get_connection()
    try:
        ctx = load_context(conn, patient)
        require_enrollment(ctx)
        sender_role = submitted_by(ctx)  # self → patient, caregiver → caregiver
        sender_role = "caregiver" if sender_role == "caregiver" else "patient"
        sender_name = ctx["episode"]["patient_name"]
        stamp = event_iso(ctx)

        if body.thread_id is not None:
            thread = conn.execute(
                "SELECT * FROM app.message_thread WHERE id = ? AND fin = ?",
                (body.thread_id, ctx["fin"]),
            ).fetchone()
            if thread is None:
                raise HTTPException(status_code=404, detail="Thread not found")
            thread_id = thread["id"]
        else:
            subject = (body.subject or text[:60]).strip() or "Question for my care team"
            cur = conn.execute(
                """
                INSERT INTO app.message_thread (
                    patient_id, fin, subject, status, created_at,
                    last_message_at, unread_provider, unread_patient, org_id
                ) VALUES (?, ?, ?, 'open', ?, ?, 0, 0, ?)
                """,
                (ctx["patient_id"], ctx["fin"], subject, stamp, stamp, ctx["org_id"]),
            )
            thread_id = int(cur.lastrowid)

        cur = conn.execute(
            """
            INSERT INTO app.message (
                thread_id, sender_role, sender_name, body, sent_at, org_id
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (thread_id, sender_role, sender_name, text, stamp, ctx["org_id"]),
        )
        message_id = int(cur.lastrowid)

        conn.execute(
            """
            UPDATE app.message_thread
            SET last_message_at = ?,
                unread_provider = unread_provider + 1,
                status = 'open'
            WHERE id = ?
            """,
            (stamp, thread_id),
        )

        signal_id = write_signal(
            conn,
            ctx,
            kind="help_request" if body.urgent else "checkin_done",
            severity="yellow" if body.urgent else "green",
            detail={
                "event": "message_sent",
                "thread_id": thread_id,
                "urgent": body.urgent,
                "preview": text[:120],
            },
        )

        notified = False
        if body.urgent:
            enqueue(
                conn,
                ctx,
                kind="app_help_request",
                severity="yellow",
                title="Patient asked for help",
                summary=text[:160],
                priority=15,
                assigned_role="Ortho navigator",
                source_type="message_thread",
                source_id=str(thread_id),
                signal_event_id=signal_id,
            )
            notified = True

        write_audit(
            conn,
            ctx,
            action="message.send",
            entity_type="message",
            entity_id=str(message_id),
            detail={"thread_id": thread_id, "urgent": body.urgent},
        )
        conn.commit()

        row = conn.execute("SELECT * FROM app.message WHERE id = ?", (message_id,)).fetchone()
    finally:
        conn.close()

    ack = (
        "Sent — we've flagged this as urgent and your navigator will see it right away."
        if body.urgent
        else "Sent. Your care team usually replies within one business day."
    )
    return SendResponse(
        thread_id=thread_id,
        message=MessageOut(
            id=row["id"],
            sender_role=row["sender_role"],
            sender_name=row["sender_name"],
            body=row["body"],
            sent_at=row["sent_at"],
            read_at=row["read_at"],
        ),
        acknowledgement=ack,
        care_team_notified=notified,
    )


@router.post("/messages/{thread_id}/read")
def mark_read(
    thread_id: int, patient: Dict[str, Any] = Depends(get_current_patient)
) -> Dict[str, Any]:
    conn = get_connection()
    try:
        ctx = load_context(conn, patient)
        require_enrollment(ctx)
        thread = conn.execute(
            "SELECT id FROM app.message_thread WHERE id = ? AND fin = ?",
            (thread_id, ctx["fin"]),
        ).fetchone()
        if thread is None:
            raise HTTPException(status_code=404, detail="Thread not found")
        stamp = now_iso()
        conn.execute(
            """
            UPDATE app.message SET read_at = ?
            WHERE thread_id = ? AND sender_role = 'care_team' AND read_at IS NULL
            """,
            (stamp, thread_id),
        )
        conn.execute(
            "UPDATE app.message_thread SET unread_patient = 0 WHERE id = ?", (thread_id,)
        )
        conn.commit()
    finally:
        conn.close()
    return {"thread_id": thread_id, "unread_patient": 0}
