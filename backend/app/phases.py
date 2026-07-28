"""Episode phase + milestone derivation for the patient companion app.

The 30-day TEAM episode is presented to patients as **phases and milestones**,
never as a day counter — "you're on track to be walking with a cane" rather
than "day 14 of 30". This module owns that translation.

Phases are derived from discharge disposition + the as-of clock
(backend/app/clock.py — no module may call date.today() for business logic):

    inpatient        admit → discharge
    snf | irf        post-acute stay (disposition 03 / 62)
    transition_home  first week at home (or first week after post-acute)
    home_recovery    rest of the 30-day window
    completed        past window_end

Milestones are templated per episode, given target dates relative to discharge,
and then marked met/missed from evidence the patient generates (check-ins, PT
logs, med doses, checklists, appointment attendance). Rows persist in
app.episode_milestone so the dashboard renders the same set the patient sees.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

EPISODE_WINDOW_DAYS = 30

# Days at home before "transition" becomes "recovery".
TRANSITION_HOME_DAYS = 7

# Nominal post-acute length of stay per disposition, used to place the
# transition-home boundary when we have no facility discharge date. The cohort
# carries no SNF/IRF discharge event, so this is a demo approximation.
POST_ACUTE_DAYS = {"03": 14, "62": 12}

PHASE_LABELS = {
    "inpatient": "In the hospital",
    "snf": "At the skilled nursing facility",
    "irf": "At the rehabilitation facility",
    "transition_home": "Settling in at home",
    "home_recovery": "Recovering at home",
    "completed": "Recovery window complete",
}

PHASE_ORDER = ["inpatient", "snf", "irf", "transition_home", "home_recovery", "completed"]


def _dispo_phase(disposition_code: Optional[str], disposition: Optional[str]) -> Optional[str]:
    """Post-acute phase for a disposition, or None for home dispositions."""
    if disposition_code == "03":
        return "snf"
    if disposition_code == "62":
        return "irf"
    d = (disposition or "").lower()
    if "skilled nursing" in d:
        return "snf"
    if "rehab" in d or "irf" in d:
        return "irf"
    return None


def resolve_phase(
    *,
    admit_date: Optional[date],
    discharge_date: Optional[date],
    disposition_code: Optional[str],
    disposition: Optional[str],
    as_of: date,
) -> Dict[str, Any]:
    """Return the current phase plus the boundary dates that define it."""
    post_acute = _dispo_phase(disposition_code, disposition)
    window_end = (
        discharge_date + timedelta(days=EPISODE_WINDOW_DAYS) if discharge_date else None
    )

    if discharge_date is None or (admit_date and as_of < admit_date):
        phase = "inpatient"
    elif as_of < discharge_date:
        phase = "inpatient"
    elif window_end and as_of > window_end:
        phase = "completed"
    else:
        home_arrival = discharge_date
        if post_acute:
            stay = POST_ACUTE_DAYS.get(disposition_code or "", 14)
            home_arrival = discharge_date + timedelta(days=stay)
            if as_of < home_arrival:
                phase = post_acute
            elif as_of < home_arrival + timedelta(days=TRANSITION_HOME_DAYS):
                phase = "transition_home"
            else:
                phase = "home_recovery"
        else:
            if as_of < discharge_date + timedelta(days=TRANSITION_HOME_DAYS):
                phase = "transition_home"
            else:
                phase = "home_recovery"

    home_arrival = discharge_date
    if post_acute and discharge_date:
        home_arrival = discharge_date + timedelta(
            days=POST_ACUTE_DAYS.get(disposition_code or "", 14)
        )

    return {
        "phase": phase,
        "phase_label": PHASE_LABELS.get(phase, phase),
        "post_acute_phase": post_acute,
        "discharge_date": discharge_date.isoformat() if discharge_date else None,
        "home_arrival_date": home_arrival.isoformat() if home_arrival else None,
        "window_end": window_end.isoformat() if window_end else None,
    }


# ---------------------------------------------------------------------------
# Milestone templates
# ---------------------------------------------------------------------------
# offset = days after discharge. `evidence` names the signal that marks it met
# (interpreted in routers/timeline.py). Labels are outcome-framed, second
# person, and free of day counts.

_COMMON_MILESTONES: List[Dict[str, Any]] = [
    {
        "code": "first_checkin",
        "phase": "transition_home",
        "label": "Daily check-ins under way",
        "offset": 1,
        "evidence": "checkin_any",
    },
    {
        "code": "pt_started",
        "phase": "transition_home",
        "label": "Home exercises started",
        "offset": 3,
        "evidence": "pt_any",
    },
    {
        "code": "med_routine",
        "phase": "transition_home",
        "label": "Blood thinner part of your daily routine",
        "offset": 7,
        "evidence": "med_streak_5",
    },
    {
        "code": "home_safety_done",
        "phase": "transition_home",
        "label": "Home set up safely",
        "offset": 4,
        "evidence": "checklist_home_safety",
    },
    {
        "code": "pcp_visit",
        "phase": "transition_home",
        "label": "Primary care visit done",
        "offset": 10,
        "evidence": "appointment_pcp",
    },
    {
        "code": "walker_steady",
        "phase": "transition_home",
        "label": "Steady walking with your walker",
        "offset": 10,
        "evidence": "mobility_walker",
    },
    {
        "code": "surgeon_followup",
        "phase": "home_recovery",
        "label": "Surgeon follow-up done",
        "offset": 16,
        "evidence": "appointment_surgeon",
    },
    {
        "code": "pt_halfway",
        "phase": "home_recovery",
        "label": "Keeping up with your exercise plan",
        "offset": 18,
        "evidence": "pt_adherence_50",
    },
    {
        "code": "walker_to_cane",
        "phase": "home_recovery",
        "label": "Getting around with a cane",
        "offset": 22,
        "evidence": "mobility_cane",
    },
    {
        "code": "pain_controlled",
        "phase": "home_recovery",
        "label": "Pain well controlled",
        "offset": 24,
        "evidence": "pain_under_4",
    },
    {
        "code": "independent_adl",
        "phase": "home_recovery",
        "label": "Managing daily activities on your own",
        "offset": 28,
        "evidence": "mobility_independent",
    },
    {
        "code": "episode_complete",
        "phase": "home_recovery",
        "label": "Recovery program complete",
        "offset": 30,
        "evidence": "window_end",
    },
]

_POST_ACUTE_MILESTONES: List[Dict[str, Any]] = [
    {
        "code": "snf_therapy_started",
        "phase": "snf",
        "label": "Therapy started at the facility",
        "offset": 2,
        "evidence": "pt_any",
    },
    {
        "code": "snf_discharge_ready",
        "phase": "snf",
        "label": "Ready to go home from the facility",
        "offset": 12,
        "evidence": "checklist_snf_discharge_readiness",
    },
]


def milestone_template(
    *,
    disposition_code: Optional[str],
    disposition: Optional[str],
    has_anticoagulant: bool,
) -> List[Dict[str, Any]]:
    """Milestone set for one episode, ordered by target offset."""
    post_acute = _dispo_phase(disposition_code, disposition)
    items: List[Dict[str, Any]] = []

    if post_acute:
        for m in _POST_ACUTE_MILESTONES:
            item = dict(m)
            item["phase"] = post_acute
            items.append(item)

    for m in _COMMON_MILESTONES:
        if m["code"] == "med_routine" and not has_anticoagulant:
            continue
        items.append(dict(m))

    items.sort(key=lambda m: m["offset"])
    for i, item in enumerate(items):
        item["sort_order"] = i
    return items
