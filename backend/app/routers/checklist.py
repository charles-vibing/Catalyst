"""Patient app: phase-gated checklists (A9).

  GET  /api/patient/checklists           — which checklists are unlocked now
  GET  /api/patient/checklist/{code}     — items + current answers
  POST /api/patient/checklist/{code}     — save answers

Two checklists, each gated to a phase (backend/app/catalog.py):

  snf_discharge_readiness — only while at a SNF/IRF. Can the patient walk,
      transfer, manage stairs, and do they understand their weight-bearing
      limit. A "no" on a critical item is what the SNF liaison needs to see
      before a discharge date is set.
  home_safety — from the transition-home phase onward. Trip hazards, grab bars,
      reachable phone. Most post-hip-fracture falls happen at home in the first
      weeks, so this is the highest-yield thing a patient can do unprompted.

Requesting a checklist outside its phase returns 409 rather than hiding it, so
the app can explain *why* it's locked instead of silently omitting a tab.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import get_current_patient
from ..catalog import CHECKLIST_META, checklist_codes_for_phase
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

ANSWERS = ["yes", "no", "na"]


class ItemOut(BaseModel):
    item_code: str
    label: str
    help_text: Optional[str]
    critical: bool
    answer: Optional[str]
    note: Optional[str]
    answered_at: Optional[str]


class ChecklistOut(BaseModel):
    meta: Dict[str, Any]
    checklist_code: str
    title: str
    intro: str
    phase: str
    unlocked: bool
    items: List[ItemOut]
    progress: Dict[str, Any]


class AvailableOut(BaseModel):
    meta: Dict[str, Any]
    phase: str
    available: List[Dict[str, Any]]


class AnswerIn(BaseModel):
    item_code: str
    answer: str
    note: Optional[str] = None


class SaveBody(BaseModel):
    answers: List[AnswerIn]


class SaveResponse(BaseModel):
    checklist_code: str
    saved: int
    progress: Dict[str, Any]
    acknowledgement: str
    flagged_items: List[str]
    milestones_met: List[str]


def _load_items(conn, ctx: Dict[str, Any], code: str) -> List[ItemOut]:
    rows = conn.execute(
        """
        SELECT i.item_code, i.label, i.help_text, i.critical,
               r.answer, r.note, r.answered_at
        FROM app.checklist_item i
        LEFT JOIN app.checklist_response r
          ON r.checklist_code = i.checklist_code
         AND r.item_code = i.item_code
         AND r.fin = ?
        WHERE i.checklist_code = ?
        ORDER BY i.sort_order
        """,
        (ctx["fin"], code),
    ).fetchall()
    return [
        ItemOut(
            item_code=r["item_code"],
            label=r["label"],
            help_text=r["help_text"],
            critical=bool(r["critical"]),
            answer=r["answer"],
            note=r["note"],
            answered_at=r["answered_at"],
        )
        for r in rows
    ]


def _progress(items: List[ItemOut]) -> Dict[str, Any]:
    answered = [i for i in items if i.answer]
    blockers = [i.item_code for i in items if i.critical and i.answer == "no"]
    critical_total = len([i for i in items if i.critical])
    critical_ok = len([i for i in items if i.critical and i.answer in ("yes", "na")])
    return {
        "answered": len(answered),
        "total": len(items),
        "pct": round(100 * len(answered) / len(items)) if items else None,
        "critical_total": critical_total,
        "critical_cleared": critical_ok,
        "blockers": blockers,
        "complete": critical_total > 0 and critical_ok >= critical_total,
    }


@router.get("/checklists", response_model=AvailableOut)
def list_available(
    patient: Dict[str, Any] = Depends(get_current_patient),
) -> AvailableOut:
    conn = get_connection()
    try:
        ctx = load_context(conn, patient)
        require_enrollment(ctx)
        codes = checklist_codes_for_phase(
            ctx["phase"], ctx["phase_detail"]["post_acute_phase"]
        )
        available = []
        for code in codes:
            items = _load_items(conn, ctx, code)
            meta = CHECKLIST_META.get(code, {})
            available.append(
                {
                    "checklist_code": code,
                    "title": meta.get("title", code),
                    "intro": meta.get("intro"),
                    "progress": _progress(items),
                }
            )
    finally:
        conn.close()
    return AvailableOut(
        meta={"as_of": ctx["as_of"].isoformat(), "fin": ctx["fin"]},
        phase=ctx["phase"],
        available=available,
    )


@router.get("/checklist/{checklist_code}", response_model=ChecklistOut)
def get_checklist(
    checklist_code: str, patient: Dict[str, Any] = Depends(get_current_patient)
) -> ChecklistOut:
    if checklist_code not in CHECKLIST_META:
        raise HTTPException(status_code=404, detail=f"Unknown checklist {checklist_code!r}")

    conn = get_connection()
    try:
        ctx = load_context(conn, patient)
        require_enrollment(ctx)
        unlocked = checklist_code in checklist_codes_for_phase(
            ctx["phase"], ctx["phase_detail"]["post_acute_phase"]
        )
        items = _load_items(conn, ctx, checklist_code)
    finally:
        conn.close()

    meta = CHECKLIST_META[checklist_code]
    return ChecklistOut(
        meta={
            "as_of": ctx["as_of"].isoformat(),
            "fin": ctx["fin"],
            "current_phase": ctx["phase"],
        },
        checklist_code=checklist_code,
        title=meta["title"],
        intro=meta["intro"],
        phase=meta["phase"],
        unlocked=unlocked,
        items=items,
        progress=_progress(items),
    )


@router.post("/checklist/{checklist_code}", response_model=SaveResponse)
def save_checklist(
    checklist_code: str,
    body: SaveBody,
    patient: Dict[str, Any] = Depends(get_current_patient),
) -> SaveResponse:
    if checklist_code not in CHECKLIST_META:
        raise HTTPException(status_code=404, detail=f"Unknown checklist {checklist_code!r}")
    for a in body.answers:
        if a.answer not in ANSWERS:
            raise HTTPException(status_code=400, detail=f"answer must be one of {ANSWERS}")

    conn = get_connection()
    try:
        ctx = load_context(conn, patient)
        require_enrollment(ctx)
        if checklist_code not in checklist_codes_for_phase(
            ctx["phase"], ctx["phase_detail"]["post_acute_phase"]
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{checklist_code} is not available during the "
                    f"{ctx['phase']} phase"
                ),
            )

        valid = {
            r["item_code"]
            for r in conn.execute(
                "SELECT item_code FROM app.checklist_item WHERE checklist_code = ?",
                (checklist_code,),
            ).fetchall()
        }
        unknown = [a.item_code for a in body.answers if a.item_code not in valid]
        if unknown:
            raise HTTPException(
                status_code=400, detail=f"Unknown item_code(s): {unknown}"
            )

        by = submitted_by(ctx)
        stamp = event_iso(ctx)
        for a in body.answers:
            conn.execute(
                """
                INSERT INTO app.checklist_response (
                    patient_id, fin, checklist_code, item_code, answer, note,
                    answered_at, answered_by, org_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fin, checklist_code, item_code) DO UPDATE SET
                    answer = excluded.answer,
                    note = excluded.note,
                    answered_at = excluded.answered_at,
                    answered_by = excluded.answered_by
                """,
                (
                    ctx["patient_id"],
                    ctx["fin"],
                    checklist_code,
                    a.item_code,
                    a.answer,
                    a.note,
                    stamp,
                    by,
                    ctx["org_id"],
                ),
            )

        items = _load_items(conn, ctx, checklist_code)
        progress = _progress(items)
        blockers = progress["blockers"]
        label_by_code = {i.item_code: i.label for i in items}

        severity = "yellow" if blockers else "green"
        signal_id = write_signal(
            conn,
            ctx,
            kind="checkin_done",
            severity=severity,
            detail={
                "event": "checklist_saved",
                "checklist_code": checklist_code,
                "answered": progress["answered"],
                "total": progress["total"],
                "blockers": blockers,
            },
        )

        # A critical "no" is provider-actionable: home safety gaps drive falls,
        # SNF readiness gaps drive premature discharge.
        if blockers:
            enqueue(
                conn,
                ctx,
                kind="app_symptom",
                severity="yellow",
                title=(
                    f"{CHECKLIST_META[checklist_code]['title']}: "
                    f"{len(blockers)} item(s) not in place"
                ),
                summary="; ".join(label_by_code.get(b, b) for b in blockers)[:300],
                priority=25,
                assigned_role=(
                    "SNF liaison"
                    if checklist_code == "snf_discharge_readiness"
                    else "Ortho navigator"
                ),
                source_type="checklist_response",
                source_id=checklist_code,
                signal_event_id=signal_id,
            )

        write_audit(
            conn,
            ctx,
            action="checklist.save",
            entity_type="checklist_response",
            entity_id=f"{ctx['fin']}:{checklist_code}",
            detail={"answered": progress["answered"], "blockers": blockers},
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
    finally:
        conn.close()

    if blockers:
        ack = (
            f"Saved. We've let your care team know about "
            f"{len(blockers)} thing{'s' if len(blockers) > 1 else ''} that "
            "still need sorting — that's what they're there for."
        )
    elif progress["complete"]:
        ack = "Saved — everything important is in place. Nice work."
    else:
        ack = "Saved. You can come back and finish the rest any time."

    return SaveResponse(
        checklist_code=checklist_code,
        saved=len(body.answers),
        progress=progress,
        acknowledgement=ack,
        flagged_items=[label_by_code.get(b, b) for b in blockers],
        milestones_met=newly_met,
    )
