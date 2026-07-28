"""Patient app: appointments (A7 / A11).

  GET  /api/patient/appointments               — upcoming + past
  POST /api/patient/appointments/{id}/confirm  — "I'll be there"
  POST /api/patient/appointments/{id}/attended — "Did you go?" → yes/no

Seeded from the cohort's referrals (main.referral carries a real
appointment_datetime for primary care) plus generated surgeon and PT visits,
because the cohort has no referral rows for those.

Answering "did you attend?" on a PCP appointment writes
app.referral_status_event — the same table the dashboard's PCP tracker (D8)
reads for completed / no_show overrides. That closes the loop in
core-functionality.md §C: "PCP attend / no-show → PCP referral status".

Reminders are in-app only (TODO.md); `due_soon` is computed against the as-of
clock so the frozen demo still shows a live-looking reminder.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import get_current_patient
from ..db import get_connection
from ..patient_ctx import (
    event_iso,
    load_context,
    now_iso,
    parse_date,
    refresh_milestones,
    require_enrollment,
    write_audit,
    write_signal,
)

router = APIRouter(prefix="/api/patient", tags=["patient"])

# Nominal offsets (days after discharge) for visits the cohort doesn't carry.
SURGEON_FOLLOWUP_DAYS = 14
PT_FIRST_VISIT_DAYS = 3
DUE_SOON_DAYS = 3

KIND_LABELS = {
    "surgeon": "Surgeon follow-up",
    "pcp": "Primary care follow-up",
    "pt": "Physical therapy",
    "home_health": "Home health visit",
}


class AppointmentOut(BaseModel):
    id: int
    kind: str
    title: str
    provider_name: Optional[str]
    scheduled_at: Optional[str]
    location: Optional[str]
    confirmed: bool
    attended: Optional[bool]
    source: str
    is_past: bool
    due_soon: bool


class ListResponse(BaseModel):
    meta: Dict[str, Any]
    upcoming: List[AppointmentOut]
    past: List[AppointmentOut]
    needs_attendance_answer: List[AppointmentOut]


class AttendedBody(BaseModel):
    attended: bool
    note: Optional[str] = None


def ensure_appointments(conn, ctx: Dict[str, Any]) -> None:
    """Materialise app.appointment for this episode once."""
    existing = conn.execute(
        "SELECT COUNT(*) FROM app.appointment WHERE fin = ?", (ctx["fin"],)
    ).fetchone()[0]
    if existing:
        return

    ep = ctx["episode"]
    discharge = ctx["discharge_date"]

    # 1. Real referrals from the cohort.
    referrals = conn.execute(
        """
        SELECT id, type, referred_to, appointment_datetime, status
        FROM referral WHERE fin = ?
        """,
        (ctx["fin"],),
    ).fetchall()
    for r in referrals:
        rtype = (r["type"] or "").lower()
        if "primary care" in rtype:
            kind = "pcp"
        elif "home health" in rtype:
            kind = "home_health"
        elif "rehab" in rtype or "hospice" in rtype:
            continue  # facility transfers, not patient-facing appointments
        else:
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO app.appointment (
                patient_id, fin, kind, title, provider_name, scheduled_at,
                location, source, referral_id, confirmed, org_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'referral', ?, 0, ?)
            """,
            (
                ctx["patient_id"],
                ctx["fin"],
                kind,
                KIND_LABELS.get(kind, kind),
                r["referred_to"],
                r["appointment_datetime"],
                None,
                r["id"],
                ctx["org_id"],
            ),
        )

    # 2. Surgeon follow-up and first PT visit — not in the cohort's referrals.
    if discharge:
        surgeon = ep["attending_name"]
        for kind, offset, provider, location in (
            (
                "surgeon",
                SURGEON_FOLLOWUP_DAYS,
                surgeon,
                "Memorial General Orthopedic Clinic",
            ),
            ("pt", PT_FIRST_VISIT_DAYS, "Memorial General Rehabilitation", None),
        ):
            when = (discharge + timedelta(days=offset)).isoformat() + "T10:00:00-06:00"
            conn.execute(
                """
                INSERT OR IGNORE INTO app.appointment (
                    patient_id, fin, kind, title, provider_name, scheduled_at,
                    location, source, confirmed, org_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'seeded', 0, ?)
                """,
                (
                    ctx["patient_id"],
                    ctx["fin"],
                    kind,
                    KIND_LABELS[kind],
                    provider,
                    when,
                    location,
                    ctx["org_id"],
                ),
            )


def _to_out(row, as_of) -> AppointmentOut:
    sched = parse_date(row["scheduled_at"])
    is_past = bool(sched and sched < as_of)
    due_soon = bool(
        sched and as_of <= sched <= as_of + timedelta(days=DUE_SOON_DAYS)
    )
    return AppointmentOut(
        id=row["id"],
        kind=row["kind"],
        title=row["title"],
        provider_name=row["provider_name"],
        scheduled_at=row["scheduled_at"],
        location=row["location"],
        confirmed=bool(row["confirmed"]),
        attended=None if row["attended"] is None else bool(row["attended"]),
        source=row["source"],
        is_past=is_past,
        due_soon=due_soon,
    )


@router.get("/appointments", response_model=ListResponse)
def list_appointments(
    patient: Dict[str, Any] = Depends(get_current_patient),
) -> ListResponse:
    conn = get_connection()
    try:
        ctx = load_context(conn, patient)
        require_enrollment(ctx)
        ensure_appointments(conn, ctx)
        conn.commit()
        rows = conn.execute(
            "SELECT * FROM app.appointment WHERE fin = ? ORDER BY scheduled_at",
            (ctx["fin"],),
        ).fetchall()
    finally:
        conn.close()

    as_of = ctx["as_of"]
    items = [_to_out(r, as_of) for r in rows]
    upcoming = [a for a in items if not a.is_past]
    past = [a for a in items if a.is_past]
    return ListResponse(
        meta={
            "as_of": as_of.isoformat(),
            "as_of_mode": ctx["as_of_mode"],
            "fin": ctx["fin"],
            "reminders": "in_app_only",
        },
        upcoming=upcoming,
        past=past,
        needs_attendance_answer=[a for a in past if a.attended is None],
    )


@router.post("/appointments/{appointment_id}/confirm", response_model=AppointmentOut)
def confirm_appointment(
    appointment_id: int, patient: Dict[str, Any] = Depends(get_current_patient)
) -> AppointmentOut:
    conn = get_connection()
    try:
        ctx = load_context(conn, patient)
        require_enrollment(ctx)
        row = conn.execute(
            "SELECT * FROM app.appointment WHERE id = ? AND fin = ?",
            (appointment_id, ctx["fin"]),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Appointment not found")

        conn.execute(
            "UPDATE app.appointment SET confirmed = 1, confirmed_at = ? WHERE id = ?",
            (event_iso(ctx), appointment_id),
        )
        write_audit(
            conn,
            ctx,
            action="appointment.confirm",
            entity_type="appointment",
            entity_id=str(appointment_id),
            detail={"kind": row["kind"], "scheduled_at": row["scheduled_at"]},
        )
        conn.commit()
        updated = conn.execute(
            "SELECT * FROM app.appointment WHERE id = ?", (appointment_id,)
        ).fetchone()
    finally:
        conn.close()
    return _to_out(updated, ctx["as_of"])


@router.post("/appointments/{appointment_id}/attended", response_model=AppointmentOut)
def record_attendance(
    appointment_id: int,
    body: AttendedBody,
    patient: Dict[str, Any] = Depends(get_current_patient),
) -> AppointmentOut:
    """Record whether the patient attended.

    For PCP visits this also writes app.referral_status_event so the dashboard's
    PCP tracker reflects completed / no_show without a navigator having to call.
    """
    conn = get_connection()
    try:
        ctx = load_context(conn, patient)
        require_enrollment(ctx)
        row = conn.execute(
            "SELECT * FROM app.appointment WHERE id = ? AND fin = ?",
            (appointment_id, ctx["fin"]),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Appointment not found")

        conn.execute(
            "UPDATE app.appointment SET attended = ?, attended_at = ? WHERE id = ?",
            (int(body.attended), event_iso(ctx), appointment_id),
        )

        if row["kind"] == "pcp":
            conn.execute(
                """
                INSERT INTO app.referral_status_event (
                    patient_id, fin, referral_id, status, noted_at, noted_by, note, org_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ctx["patient_id"],
                    ctx["fin"],
                    row["referral_id"],
                    "completed" if body.attended else "no_show",
                    event_iso(ctx),
                    ctx["actor_id"],
                    body.note or "Reported in patient app",
                    ctx["org_id"],
                ),
            )

        write_signal(
            conn,
            ctx,
            kind="checkin_done" if body.attended else "help_request",
            severity="green" if body.attended else "yellow",
            detail={
                "event": "appointment_attendance",
                "kind": row["kind"],
                "title": row["title"],
                "attended": body.attended,
            },
        )
        write_audit(
            conn,
            ctx,
            action="appointment.attendance",
            entity_type="appointment",
            entity_id=str(appointment_id),
            detail={"kind": row["kind"], "attended": body.attended},
        )
        refresh_milestones(conn, ctx)
        conn.commit()
        updated = conn.execute(
            "SELECT * FROM app.appointment WHERE id = ?", (appointment_id,)
        ).fetchone()
    finally:
        conn.close()
    return _to_out(updated, ctx["as_of"])
