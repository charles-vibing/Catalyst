"""Triage queue API — list / assign / resolve (M6 framework)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..auth import get_current_user
from ..db import get_connection

router = APIRouter(prefix="/api", tags=["queue"])

RESOLVE_ACTIONS = {"call_caregiver", "call_patient", "mark_resolved"}


class QueueItemOut(BaseModel):
    id: int
    kind: str
    severity: str
    title: str
    summary: Optional[str]
    patient_id: int
    patient_name: Optional[str]
    fin: Optional[str]
    priority: Optional[int]
    assigned_role: Optional[str]
    status: str
    created_at: Optional[str]
    resolution_action: Optional[str] = None
    resolution_note: Optional[str] = None
    resolved_at: Optional[str] = None


class QueueListResponse(BaseModel):
    items: List[QueueItemOut]
    meta: Dict[str, Any]


class ResolveBody(BaseModel):
    action: str = Field(..., description="call_caregiver | call_patient | mark_resolved")
    note: Optional[str] = None


class AssignBody(BaseModel):
    role: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_audit(
    conn,
    *,
    user: Dict[str, str],
    action: str,
    entity_id: str,
    patient_id: Optional[int],
    detail: Dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO audit_event (
            actor_id, actor_role, action, entity_type, entity_id,
            patient_id, org_id, detail_json
        ) VALUES (?, ?, ?, 'queue_item', ?, ?, ?, ?)
        """,
        (
            user["id"],
            user.get("role"),
            action,
            entity_id,
            patient_id,
            user["org_id"],
            json.dumps(detail),
        ),
    )


def _row_to_item(r) -> QueueItemOut:
    return QueueItemOut(
        id=r["id"],
        kind=r["kind"] or "manual",
        severity=r["severity"] or "yellow",
        title=r["title"] or "",
        summary=r["summary"],
        patient_id=r["patient_id"],
        patient_name=r["patient_name"],
        fin=r["fin"],
        priority=r["priority"],
        assigned_role=r["assigned_role"],
        status=r["status"],
        created_at=r["created_at"],
        resolution_action=r["resolution_action"] if "resolution_action" in r.keys() else None,
        resolution_note=r["resolution_note"],
        resolved_at=r["resolved_at"],
    )


@router.get("/queue", response_model=QueueListResponse)
def list_queue(
    status: str = Query("open", description="open | resolved | all"),
    user: Dict[str, str] = Depends(get_current_user),
) -> QueueListResponse:
    conn = get_connection()
    try:
        if status == "all":
            rows = conn.execute(
                """
                SELECT q.*,
                       p.family_name || ', ' || p.given_name AS patient_name
                FROM queue_item q
                JOIN patient p ON p.patient_id = q.patient_id
                WHERE q.org_id = ?
                ORDER BY
                  CASE q.status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END,
                  COALESCE(q.priority, 999),
                  q.created_at DESC
                """,
                (user["org_id"],),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT q.*,
                       p.family_name || ', ' || p.given_name AS patient_name
                FROM queue_item q
                JOIN patient p ON p.patient_id = q.patient_id
                WHERE q.org_id = ? AND q.status = ?
                ORDER BY COALESCE(q.priority, 999), q.created_at DESC
                """,
                (user["org_id"], status),
            ).fetchall()
    finally:
        conn.close()

    items = [_row_to_item(r) for r in rows]
    return QueueListResponse(
        items=items,
        meta={"org_id": user["org_id"], "status": status, "total": len(items)},
    )


@router.post("/queue/{item_id}/resolve", response_model=QueueItemOut)
def resolve_queue_item(
    item_id: int,
    body: ResolveBody,
    user: Dict[str, str] = Depends(get_current_user),
) -> QueueItemOut:
    if body.action not in RESOLVE_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"action must be one of {sorted(RESOLVE_ACTIONS)}",
        )

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM queue_item WHERE id = ? AND org_id = ?",
            (item_id, user["org_id"]),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Queue item not found")
        if row["status"] == "resolved":
            raise HTTPException(status_code=409, detail="Already resolved")

        note = body.note
        if not note:
            labels = {
                "call_caregiver": "Called caregiver",
                "call_patient": "Called patient",
                "mark_resolved": "Marked resolved",
            }
            note = labels.get(body.action, body.action)

        now = _now_iso()
        conn.execute(
            """
            UPDATE queue_item
            SET status = 'resolved',
                resolution_action = ?,
                resolution_note = ?,
                resolved_at = ?
            WHERE id = ?
            """,
            (body.action, note, now, item_id),
        )
        _write_audit(
            conn,
            user=user,
            action="queue.resolve",
            entity_id=str(item_id),
            patient_id=row["patient_id"],
            detail={
                "action": body.action,
                "note": note,
                "fin": row["fin"],
                "kind": row["kind"],
            },
        )
        conn.commit()
        updated = conn.execute(
            """
            SELECT q.*,
                   p.family_name || ', ' || p.given_name AS patient_name
            FROM queue_item q
            JOIN patient p ON p.patient_id = q.patient_id
            WHERE q.id = ?
            """,
            (item_id,),
        ).fetchone()
    finally:
        conn.close()

    return _row_to_item(updated)


@router.post("/queue/{item_id}/assign", response_model=QueueItemOut)
def assign_queue_item(
    item_id: int,
    body: AssignBody,
    user: Dict[str, str] = Depends(get_current_user),
) -> QueueItemOut:
    role = (body.role or "").strip()
    if not role:
        raise HTTPException(status_code=400, detail="role is required")

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM queue_item WHERE id = ? AND org_id = ?",
            (item_id, user["org_id"]),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Queue item not found")

        conn.execute(
            """
            UPDATE queue_item
            SET assigned_role = ?,
                status = CASE WHEN status = 'open' THEN 'in_progress' ELSE status END
            WHERE id = ?
            """,
            (role, item_id),
        )
        _write_audit(
            conn,
            user=user,
            action="queue.assign",
            entity_id=str(item_id),
            patient_id=row["patient_id"],
            detail={"role": role, "fin": row["fin"]},
        )
        conn.commit()
        updated = conn.execute(
            """
            SELECT q.*,
                   p.family_name || ', ' || p.given_name AS patient_name
            FROM queue_item q
            JOIN patient p ON p.patient_id = q.patient_id
            WHERE q.id = ?
            """,
            (item_id,),
        ).fetchone()
    finally:
        conn.close()

    return _row_to_item(updated)
