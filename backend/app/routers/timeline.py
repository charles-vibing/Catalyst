"""Patient app: personalised recovery timeline (A2).

  GET /api/patient/timeline

Milestone-based, not day-count-based. The headline is always framed as what the
patient is on track *for* ("You're on track to be getting around with a cane"),
with the day count deliberately absent from patient-facing copy — the 30-day
window is a payment construct, not something a recovering patient should be
counting down.

Phases come from backend/app/phases.py; milestone status is refreshed from
current evidence (check-ins, PT logs, med doses, checklists, appointments) via
patient_ctx.refresh_milestones so this view and the dashboard never disagree.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import get_current_patient
from ..db import get_connection
from ..patient_ctx import (
    checkin_adherence,
    load_context,
    med_adherence,
    pt_adherence,
    refresh_milestones,
    require_enrollment,
)
from ..phases import PHASE_LABELS, PHASE_ORDER

router = APIRouter(prefix="/api/patient", tags=["patient"])


class MilestoneOut(BaseModel):
    code: str
    phase: str
    label: str
    target_date: Optional[str]
    status: str
    met_at: Optional[str]


class PhaseOut(BaseModel):
    phase: str
    label: str
    state: str  # done | current | upcoming
    milestones_total: int
    milestones_met: int


class TimelineResponse(BaseModel):
    meta: Dict[str, Any]
    headline: str
    subhead: str
    phase: str
    phase_label: str
    phases: List[PhaseOut]
    milestones: List[MilestoneOut]
    next_milestone: Optional[MilestoneOut]
    progress: Dict[str, Any]


def _phase_sequence(post_acute: Optional[str]) -> List[str]:
    seq = ["inpatient"]
    if post_acute:
        seq.append(post_acute)
    seq += ["transition_home", "home_recovery"]
    return seq


@router.get("/timeline", response_model=TimelineResponse)
def get_timeline(
    patient: Dict[str, Any] = Depends(get_current_patient),
) -> TimelineResponse:
    conn = get_connection()
    try:
        ctx = load_context(conn, patient)
        require_enrollment(ctx)
        milestones = refresh_milestones(conn, ctx)
        conn.commit()

        checkins = checkin_adherence(conn, ctx)
        pt = pt_adherence(conn, ctx)
        meds = med_adherence(conn, ctx)
    finally:
        conn.close()

    phase = ctx["phase"]
    post_acute = ctx["phase_detail"]["post_acute_phase"]
    sequence = _phase_sequence(post_acute)

    # Per-phase rollup
    phases: List[PhaseOut] = []
    current_index = sequence.index(phase) if phase in sequence else len(sequence)
    for i, p in enumerate(sequence):
        in_phase = [m for m in milestones if m["phase"] == p]
        if phase == "completed":
            state = "done"
        elif i < current_index:
            state = "done"
        elif i == current_index:
            state = "current"
        else:
            state = "upcoming"
        phases.append(
            PhaseOut(
                phase=p,
                label=PHASE_LABELS.get(p, p),
                state=state,
                milestones_total=len(in_phase),
                milestones_met=len([m for m in in_phase if m["status"] == "met"]),
            )
        )

    met = [m for m in milestones if m["status"] == "met"]
    pending = [m for m in milestones if m["status"] == "pending"]
    missed = [m for m in milestones if m["status"] == "missed"]
    next_m = pending[0] if pending else None

    # "On track for X" framing — the next unmet milestone is the goal, not a date.
    if phase == "completed":
        headline = "You've finished your 30-day recovery program"
        subhead = f"{len(met)} of {len(milestones)} recovery goals reached."
    elif next_m:
        headline = f"You're on track. Next goal: {next_m['label']}"
        subhead = (
            f"{len(met)} of {len(milestones)} goals reached so far."
            if met
            else "Let's get started on your first goals."
        )
    else:
        headline = "You've reached every goal in your plan"
        subhead = "Keep up your check-ins until your recovery window closes."

    if missed and next_m:
        subhead = (
            f"{len(met)} of {len(milestones)} goals reached. "
            f"{len(missed)} to catch up on — your care team can help."
        )

    return TimelineResponse(
        meta={
            "as_of": ctx["as_of"].isoformat(),
            "as_of_mode": ctx["as_of_mode"],
            "fin": ctx["fin"],
            # Present for the provider surface and debugging; the patient UI
            # deliberately does not render a countdown.
            "days_remaining": ctx["days_remaining"],
            "window_end": ctx["phase_detail"]["window_end"],
        },
        headline=headline,
        subhead=subhead,
        phase=phase,
        phase_label=ctx["phase_detail"]["phase_label"],
        phases=phases,
        milestones=[
            MilestoneOut(
                code=m["code"],
                phase=m["phase"],
                label=m["label"],
                target_date=m["target_date"],
                status=m["status"],
                met_at=m["met_at"],
            )
            for m in milestones
        ],
        next_milestone=(
            MilestoneOut(
                code=next_m["code"],
                phase=next_m["phase"],
                label=next_m["label"],
                target_date=next_m["target_date"],
                status=next_m["status"],
                met_at=next_m["met_at"],
            )
            if next_m
            else None
        ),
        progress={
            "milestones_met": len(met),
            "milestones_total": len(milestones),
            "milestones_missed": len(missed),
            "checkin": checkins,
            "pt": pt,
            "medication": meds,
        },
    )


@router.get("/phases", response_model=List[str])
def list_phases() -> List[str]:
    """Canonical phase order — used by the app for progress rendering."""
    return PHASE_ORDER
