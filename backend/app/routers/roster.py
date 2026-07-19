"""GET /api/roster — read-only SHFFT episode roster (D1, D9 partial)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import get_current_user
from ..clock import get_as_of
from ..db import get_connection

router = APIRouter(prefix="/api", tags=["roster"])

EPISODE_WINDOW_DAYS = 30


class Episode(BaseModel):
    patient_id: int
    mrn: str
    patient_name: str
    age: Optional[int]
    sex: Optional[str]
    fin: str
    admit_date: Optional[str]
    discharge_date: Optional[str]
    window_end: Optional[str]
    ms_drg: Optional[str]
    procedure_summary: Optional[str]
    procedure_date: Optional[str]
    disposition: Optional[str]
    disposition_code: Optional[str]
    status: str
    days_remaining: Optional[int]


class RosterResponse(BaseModel):
    meta: Dict[str, Any]
    episodes: List[Episode]


def _classify(admit: Optional[date], discharge: Optional[date], as_of: date):
    """Episode status per design/as-of-date.md; returns (status, days_remaining)."""
    if admit is not None and admit > as_of:
        return "upcoming", None
    window_end = discharge + timedelta(days=EPISODE_WINDOW_DAYS) if discharge else None
    if window_end is not None and as_of > window_end:
        status = "completed"
    else:
        status = "active"
    days_remaining = max(0, (window_end - as_of).days) if window_end else None
    return status, days_remaining


def _parse_date(value: Optional[str]) -> Optional[date]:
    return date.fromisoformat(value) if value else None


def _age_years(birth: Optional[date], as_of: date) -> Optional[int]:
    if birth is None:
        return None
    years = as_of.year - birth.year
    if (as_of.month, as_of.day) < (birth.month, birth.day):
        years -= 1
    return years


@router.get("/roster", response_model=RosterResponse)
def get_roster(user: Dict[str, str] = Depends(get_current_user)) -> RosterResponse:
    as_of, mode = get_as_of()
    conn = get_connection()
    try:
        org = conn.execute(
            """
            SELECT org_id, name, short_name, city, state, is_anchor
            FROM organization
            WHERE org_id = ?
            """,
            (user["org_id"],),
        ).fetchone()
        rows = conn.execute(
            """
            SELECT patient_id, mrn, patient_name, birth_date, sex, fin,
                   admit_date, discharge_date, window_end,
                   ms_drg, procedure_summary, procedure_date,
                   discharge_disposition, discharge_disposition_code
            FROM v_roster
            ORDER BY admit_date, fin
            """
        ).fetchall()
    finally:
        conn.close()

    org_name = org["name"] if org else user["org_id"]

    episodes: List[Episode] = []
    for r in rows:
        status, days_remaining = _classify(
            _parse_date(r["admit_date"]), _parse_date(r["discharge_date"]), as_of
        )
        # Demo roster: only admitted episodes (active + completed). Upcoming
        # admits (admit > as_of) stay in the DB/views but are hidden from UI.
        if status == "upcoming":
            continue
        episodes.append(
            Episode(
                patient_id=r["patient_id"],
                mrn=r["mrn"],
                patient_name=r["patient_name"],
                age=_age_years(_parse_date(r["birth_date"]), as_of),
                sex=r["sex"],
                fin=r["fin"],
                admit_date=r["admit_date"],
                discharge_date=r["discharge_date"],
                window_end=r["window_end"],
                ms_drg=r["ms_drg"],
                procedure_summary=r["procedure_summary"],
                procedure_date=r["procedure_date"],
                disposition=r["discharge_disposition"],
                disposition_code=r["discharge_disposition_code"],
                status=status,
                days_remaining=days_remaining,
            )
        )

    counts: Dict[str, int] = {}
    for e in episodes:
        counts[e.status] = counts.get(e.status, 0) + 1

    # Active first, then completed; within each group keep admit_date order.
    status_rank = {"active": 0, "completed": 1}
    episodes.sort(
        key=lambda e: (
            status_rank.get(e.status, 9),
            e.admit_date or "",
            e.fin,
        )
    )

    return RosterResponse(
        meta={
            "as_of": as_of.isoformat(),
            "as_of_mode": mode,
            "org_id": user["org_id"],
            "org_name": org_name,
            "total": len(episodes),
            "status_counts": counts,
        },
        episodes=episodes,
    )
