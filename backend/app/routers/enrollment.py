"""Patient app: login-ish patient picker, identity, and onboarding (A1).

  GET  /api/patient/candidates  — demo picker standing in for a login screen
  GET  /api/patient/me          — identity + episode + phase + enrollment state
  POST /api/patient/enrollment  — confirm procedure / surgeon / destination

Onboarding is deliberately a *confirmation* flow: the EHR already knows the
procedure, surgeon, and discharge destination, so the patient verifies rather
than types. Confirmed values are stored separately from the cohort truth so a
mismatch stays visible to the navigator instead of overwriting the chart.

One login, used by the patient or a caregiver — distinguished only by
`relationship`. Separate caregiver accounts are post-MVP (TODO.md).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import get_current_patient, get_current_user
from ..clock import get_as_of
from ..db import get_connection
from ..patient_ctx import (
    event_iso,
    load_context,
    now_iso,
    procedure_type,
    refresh_milestones,
    write_audit,
    write_signal,
)

router = APIRouter(prefix="/api/patient", tags=["patient"])


class CandidateOut(BaseModel):
    patient_id: int
    fin: str
    mrn: str
    patient_name: str
    age: Optional[int]
    discharge_date: Optional[str]
    disposition: Optional[str]
    procedure_summary: Optional[str]
    enrolled: bool
    status: str


class EpisodeSummary(BaseModel):
    fin: str
    mrn: str
    patient_name: str
    procedure_text: Optional[str]
    procedure_type: str
    procedure_date: Optional[str]
    surgeon: Optional[str]
    admit_date: Optional[str]
    discharge_date: Optional[str]
    window_end: Optional[str]
    disposition: Optional[str]
    disposition_code: Optional[str]
    hospital: str


class EnrollmentOut(BaseModel):
    relationship: str
    confirmed_procedure_type: Optional[str]
    confirmed_procedure_text: Optional[str]
    confirmed_surgeon: Optional[str]
    confirmed_discharge_destination: Optional[str]
    contact_phone: Optional[str]
    enrolled_at: str
    status: str


class MeResponse(BaseModel):
    meta: Dict[str, Any]
    episode: EpisodeSummary
    phase: str
    phase_label: str
    enrolled: bool
    enrollment: Optional[EnrollmentOut]
    onboarding: Dict[str, Any]


class EnrollBody(BaseModel):
    relationship: str = Field(default="self", description="self | caregiver")
    confirmed_procedure_type: Optional[str] = Field(default=None, description="hip | femur")
    confirmed_procedure_text: Optional[str] = None
    confirmed_surgeon: Optional[str] = None
    confirmed_discharge_destination: Optional[str] = None
    contact_phone: Optional[str] = None


def _surgeon(episode: Dict[str, Any]) -> Optional[str]:
    """Best available surgeon name.

    The cohort has no care_team_member row with role 'Surgeon' — roles are PCP,
    Case Manager, Attending, and Hospitalist consult. For these SHFFT episodes
    the orthopaedic attending IS the operating surgeon, so that is the proxy.
    """
    if (episode.get("hospital_service") or "").lower().startswith("orthopedic"):
        return episode.get("attending_name")
    return episode.get("attending_name")


def _age(birth_date: Optional[str]) -> Optional[int]:
    as_of, _ = get_as_of()
    if not birth_date:
        return None
    from datetime import date

    b = date.fromisoformat(birth_date[:10])
    years = as_of.year - b.year
    if (as_of.month, as_of.day) < (b.month, b.day):
        years -= 1
    return years


@router.get("/candidates", response_model=List[CandidateOut])
def list_candidates(user: Dict[str, str] = Depends(get_current_user)) -> List[CandidateOut]:
    """Episodes a demo user can sign in as.

    Stands in for authentication: the app shows this list, the user picks a
    name, and the choice is sent back as the X-Catalyst-Patient header. Uses
    the staff auth stub because it runs before a patient identity exists.
    """
    as_of, _ = get_as_of()
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT v.patient_id, v.fin, v.mrn, v.patient_name, v.birth_date,
                   v.discharge_date, v.discharge_disposition, v.procedure_summary,
                   e.id AS enrollment_id
            FROM v_episode v
            LEFT JOIN app.patient_enrollment e ON e.fin = v.fin
            WHERE date(v.discharge_datetime) <= ?
              AND date(v.discharge_datetime, '+30 days') >= ?
            ORDER BY v.discharge_date DESC
            """,
            (as_of.isoformat(), as_of.isoformat()),
        ).fetchall()
    finally:
        conn.close()

    return [
        CandidateOut(
            patient_id=r["patient_id"],
            fin=r["fin"],
            mrn=r["mrn"],
            patient_name=r["patient_name"],
            age=_age(r["birth_date"]),
            discharge_date=r["discharge_date"],
            disposition=r["discharge_disposition"],
            procedure_summary=r["procedure_summary"],
            enrolled=r["enrollment_id"] is not None,
            status="active",
        )
        for r in rows
    ]


@router.get("/me", response_model=MeResponse)
def get_me(patient: Dict[str, Any] = Depends(get_current_patient)) -> MeResponse:
    conn = get_connection()
    try:
        ctx = load_context(conn, patient)
        ep = ctx["episode"]
        org = conn.execute(
            "SELECT name FROM app.organization WHERE org_id = ?", (ctx["org_id"],)
        ).fetchone()
        hospital = org["name"] if org else ctx["org_id"]
    finally:
        conn.close()

    proc_type = procedure_type(ep["procedure_summary"], ep["ms_drg"])
    enrollment = ctx["enrollment"]

    return MeResponse(
        meta={
            "as_of": ctx["as_of"].isoformat(),
            "as_of_mode": ctx["as_of_mode"],
            "org_id": ctx["org_id"],
            "org_name": hospital,
            "days_remaining": ctx["days_remaining"],
        },
        episode=EpisodeSummary(
            fin=ctx["fin"],
            mrn=ep["mrn"],
            patient_name=ep["patient_name"],
            procedure_text=ep["procedure_summary"],
            procedure_type=proc_type,
            procedure_date=ep["procedure_date"],
            surgeon=_surgeon(ep),
            admit_date=ep["admit_date"],
            discharge_date=ep["discharge_date"],
            window_end=ep["window_end"],
            disposition=ep["discharge_disposition"],
            disposition_code=ep["discharge_disposition_code"],
            hospital=hospital,
        ),
        phase=ctx["phase"],
        phase_label=ctx["phase_detail"]["phase_label"],
        enrolled=enrollment is not None,
        enrollment=EnrollmentOut(**enrollment) if enrollment else None,
        onboarding={
            # Prefilled choices the patient confirms or corrects.
            "procedure_type_options": ["hip", "femur"],
            "procedure_type_suggested": proc_type,
            "procedure_text_suggested": ep["procedure_summary"],
            "surgeon_suggested": _surgeon(ep),
            "destination_suggested": ep["discharge_disposition"],
            "destination_options": [
                "Home",
                "Home with home health agency (HHA)",
                "Skilled Nursing Facility",
                "Inpatient Rehabilitation Facility",
            ],
            "relationship_options": ["self", "caregiver"],
            "contact_phone_suggested": ep["phone_mobile"] or ep["phone_home"],
        },
    )


@router.post("/enrollment", response_model=EnrollmentOut)
def create_enrollment(
    body: EnrollBody, patient: Dict[str, Any] = Depends(get_current_patient)
) -> EnrollmentOut:
    """Create or update the enrollment record for this episode."""
    if body.relationship not in ("self", "caregiver"):
        raise HTTPException(status_code=400, detail="relationship must be self or caregiver")
    if body.confirmed_procedure_type and body.confirmed_procedure_type not in (
        "hip",
        "femur",
        "other",
    ):
        raise HTTPException(
            status_code=400, detail="confirmed_procedure_type must be hip, femur, or other"
        )

    conn = get_connection()
    try:
        ctx = load_context(conn, patient)
        ep = ctx["episode"]
        first_time = ctx["enrollment"] is None

        conn.execute(
            """
            INSERT INTO app.patient_enrollment (
                patient_id, fin, relationship, confirmed_procedure_type,
                confirmed_procedure_text, confirmed_surgeon,
                confirmed_discharge_destination, disposition_code,
                contact_phone, enrolled_at, status, org_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
            ON CONFLICT(fin) DO UPDATE SET
                relationship = excluded.relationship,
                confirmed_procedure_type = excluded.confirmed_procedure_type,
                confirmed_procedure_text = excluded.confirmed_procedure_text,
                confirmed_surgeon = excluded.confirmed_surgeon,
                confirmed_discharge_destination = excluded.confirmed_discharge_destination,
                contact_phone = excluded.contact_phone
            """,
            (
                ctx["patient_id"],
                ctx["fin"],
                body.relationship,
                body.confirmed_procedure_type
                or procedure_type(ep["procedure_summary"], ep["ms_drg"]),
                body.confirmed_procedure_text or ep["procedure_summary"],
                body.confirmed_surgeon or _surgeon(ep),
                body.confirmed_discharge_destination or ep["discharge_disposition"],
                ep["discharge_disposition_code"],
                body.contact_phone or ep["phone_mobile"] or ep["phone_home"],
                event_iso(ctx),
                ctx["org_id"],
            ),
        )

        if first_time:
            write_signal(
                conn,
                ctx,
                kind="checkin_done",
                severity="green",
                detail={"event": "enrolled", "relationship": body.relationship},
            )
        write_audit(
            conn,
            ctx,
            action="enrollment.confirm",
            entity_type="patient_enrollment",
            entity_id=ctx["fin"],
            detail={"relationship": body.relationship, "first_time": first_time},
        )

        # Enrollment is what unlocks the timeline; build it now.
        ctx["enrollment"] = {"relationship": body.relationship}
        refresh_milestones(conn, ctx)
        conn.commit()

        row = conn.execute(
            "SELECT * FROM app.patient_enrollment WHERE fin = ?", (ctx["fin"],)
        ).fetchone()
    finally:
        conn.close()

    return EnrollmentOut(**dict(row))
