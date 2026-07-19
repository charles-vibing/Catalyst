"""GET /api/episodes/{fin} — patient episode clinical detail (M2 / D4 + D9)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from ..auth import get_current_user
from ..clock import get_as_of
from ..db import get_connection
from ..paths import SandboxViolation, safe_patient_file

router = APIRouter(prefix="/api", tags=["episodes"])

EPISODE_WINDOW_DAYS = 30

# Key labs for post-discharge monitoring (LOINC + display fallbacks).
KEY_LAB_LOINCS = {
    "1751-7": "Albumin",
    "718-7": "Hemoglobin",
    "2160-0": "Creatinine",
}
KEY_LAB_DISPLAY = ("albumin", "hemoglobin", "hgb", "creatinine", "creat")

DISPOSITION_PLAYBOOK: Dict[str, Dict[str, Any]] = {
    "01": {
        "title": "Home — contact patient / caregiver",
        "bullets": [
            "Primary outreach: patient or emergency contact",
            "Expected: daily check-in once patient app is live",
            "Missed check-in = escalate within 24h",
        ],
    },
    "06": {
        "title": "Home with HHA — contact agency + patient",
        "bullets": [
            "Coordinate with home health agency nurse",
            "Patient engagement may be intermittent",
            "Watch wound / mobility / volume symptoms",
        ],
    },
    "03": {
        "title": "SNF — contact facility nurse / liaison",
        "bullets": [
            "Facility nurse is primary day-to-day contact",
            "Patient app engagement expected sparse",
            "Confirm receiving facility on discharge summary",
        ],
    },
    "62": {
        "title": "IRF — contact rehab case manager",
        "bullets": [
            "IRF therapy team owns daily mobility plan",
            "Coordinate TEAM PCP visit around IRF stay",
            "Patient app engagement expected sparse",
        ],
    },
    "50": {
        "title": "Hospice — contact hospice team",
        "bullets": [
            "Hospice owns day-to-day care",
            "TEAM monitoring is supportive / informational",
        ],
    },
    "51": {
        "title": "Hospice — contact hospice team",
        "bullets": [
            "Hospice owns day-to-day care",
            "TEAM monitoring is supportive / informational",
        ],
    },
}

DEFAULT_PLAYBOOK = {
    "title": "Post-acute — confirm care setting contacts",
    "bullets": [
        "Verify disposition and receiving facility",
        "Identify primary outreach contact",
    ],
}


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class EpisodeHeader(BaseModel):
    patient_id: int
    mrn: str
    patient_name: str
    age: Optional[int]
    sex: Optional[str]
    fin: str
    admit_date: Optional[str]
    discharge_date: Optional[str]
    admit_datetime: Optional[str]
    discharge_datetime: Optional[str]
    window_end: Optional[str]
    ms_drg: Optional[str]
    procedure_summary: Optional[str]
    procedure_date: Optional[str]
    disposition: Optional[str]
    disposition_code: Optional[str]
    principal_diagnosis: Optional[str]
    attending_name: Optional[str]
    length_of_stay_days: Optional[int]
    status: str
    days_remaining: Optional[int]


class ProblemOut(BaseModel):
    description: str
    icd10: Optional[str]
    status: Optional[str]


class MedOut(BaseModel):
    name: str
    sig: Optional[str]
    route: Optional[str]
    frequency: Optional[str]
    indication: Optional[str]


class LabOut(BaseModel):
    display: str
    value: Optional[str]
    unit: Optional[str]
    abnormal_flag: Optional[str]
    effective_at: Optional[str]


class VitalsOut(BaseModel):
    recorded_at: Optional[str]
    temp_f: Optional[float]
    heart_rate: Optional[int]
    resp_rate: Optional[int]
    bp_systolic: Optional[int]
    bp_diastolic: Optional[int]
    spo2_percent: Optional[int]
    o2_delivery: Optional[str]
    pain_score: Optional[int]


class TherapyOut(BaseModel):
    weight_bearing: Optional[str]
    recommendation: Optional[str]
    equipment: List[str]
    eval_date: Optional[str]


class CareTeamOut(BaseModel):
    role: str
    name: str


class EmergencyContact(BaseModel):
    name: Optional[str]
    relationship: Optional[str]
    phone: Optional[str]


class DispositionContext(BaseModel):
    code: Optional[str]
    label: Optional[str]
    title: str
    bullets: List[str]
    emergency_contact: EmergencyContact


class PcpOut(BaseModel):
    status: Optional[str]
    referred_to: Optional[str]
    appointment_datetime: Optional[str]
    ordered_at: Optional[str]
    gap: bool
    note: Optional[str] = None


class TimelineEvent(BaseModel):
    at: Optional[str]
    kind: str
    label: str
    detail: Optional[str] = None


class DocumentOut(BaseModel):
    document_type: str
    service_date: Optional[str]
    author: Optional[str]
    file_name: Optional[str]


class EpisodeDetailResponse(BaseModel):
    meta: Dict[str, Any]
    episode: EpisodeHeader
    problems: List[ProblemOut]
    discharge_meds: List[MedOut]
    labs: List[LabOut]
    discharge_vitals: Optional[VitalsOut]
    therapy: Optional[TherapyOut]
    care_team: List[CareTeamOut]
    disposition_context: DispositionContext
    pcp: Optional[PcpOut]
    timeline: List[TimelineEvent]
    documents: List[DocumentOut]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    return date.fromisoformat(value[:10])


def _age_years(birth: Optional[date], as_of: date) -> Optional[int]:
    if birth is None:
        return None
    years = as_of.year - birth.year
    if (as_of.month, as_of.day) < (birth.month, birth.day):
        years -= 1
    return years


def _classify(admit: Optional[date], discharge: Optional[date], as_of: date):
    if admit is not None and admit > as_of:
        return "upcoming", None
    window_end = discharge + timedelta(days=EPISODE_WINDOW_DAYS) if discharge else None
    if window_end is not None and as_of > window_end:
        status = "completed"
    else:
        status = "active"
    days_remaining = max(0, (window_end - as_of).days) if window_end else None
    return status, days_remaining


def _is_key_lab(loinc: Optional[str], display: str) -> Optional[str]:
    if loinc and loinc in KEY_LAB_LOINCS:
        return KEY_LAB_LOINCS[loinc]
    d = (display or "").lower()
    for token in KEY_LAB_DISPLAY:
        if token in d:
            if "albumin" in d:
                return "Albumin"
            if "hemoglobin" in d or d.startswith("hgb") or " hgb" in d:
                return "Hemoglobin"
            if "creatinine" in d or "creat" in d:
                return "Creatinine"
    return None


def _lab_value(row) -> Optional[str]:
    if row["value_num"] is not None:
        v = row["value_num"]
        if isinstance(v, float) and v == int(v):
            return str(int(v))
        return str(v)
    return row["value_text"]


def _parse_equipment(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x) for x in data]
    except (json.JSONDecodeError, TypeError):
        pass
    return [raw]


def _playbook(code: Optional[str], label: Optional[str]) -> Dict[str, Any]:
    if code and code in DISPOSITION_PLAYBOOK:
        return DISPOSITION_PLAYBOOK[code]
    # Fallback by label keywords
    d = (label or "").lower()
    if "skilled nursing" in d or d == "snf":
        return DISPOSITION_PLAYBOOK["03"]
    if "rehab" in d or "irf" in d:
        return DISPOSITION_PLAYBOOK["62"]
    if "home health" in d or "hha" in d:
        return DISPOSITION_PLAYBOOK["06"]
    if "hospice" in d:
        return DISPOSITION_PLAYBOOK["50"]
    if "home" in d:
        return DISPOSITION_PLAYBOOK["01"]
    return DEFAULT_PLAYBOOK


def _org_name(conn, org_id: str) -> str:
    row = conn.execute(
        "SELECT name FROM organization WHERE org_id = ?", (org_id,)
    ).fetchone()
    return row["name"] if row else org_id


def _build_timeline(
    *,
    admit_dt: Optional[str],
    procedure_date: Optional[str],
    procedure_summary: Optional[str],
    therapy_eval_date: Optional[str],
    weight_bearing: Optional[str],
    discharge_dt: Optional[str],
    disposition: Optional[str],
    ms_drg: Optional[str],
    pcp: Optional[PcpOut],
) -> List[TimelineEvent]:
    events: List[TimelineEvent] = []
    if admit_dt:
        events.append(
            TimelineEvent(at=admit_dt, kind="admitted", label="Admitted", detail=None)
        )
    if procedure_date:
        events.append(
            TimelineEvent(
                at=procedure_date,
                kind="procedure",
                label="Procedure",
                detail=procedure_summary,
            )
        )
    if therapy_eval_date:
        events.append(
            TimelineEvent(
                at=therapy_eval_date,
                kind="therapy_eval",
                label="Therapy evaluation",
                detail=weight_bearing,
            )
        )
    if discharge_dt:
        detail_parts = [p for p in [disposition, f"DRG {ms_drg}" if ms_drg else None] if p]
        events.append(
            TimelineEvent(
                at=discharge_dt,
                kind="discharged",
                label="Discharged",
                detail=" · ".join(detail_parts) if detail_parts else None,
            )
        )
    if pcp:
        if pcp.ordered_at:
            events.append(
                TimelineEvent(
                    at=pcp.ordered_at,
                    kind="pcp_ordered",
                    label="PCP referral ordered",
                    detail=pcp.referred_to,
                )
            )
        if pcp.appointment_datetime:
            status_l = (pcp.status or "").lower()
            if "complet" in status_l:
                kind, label = "pcp_completed", "PCP visit completed"
            elif "no" in status_l and "show" in status_l:
                kind, label = "pcp_no_show", "PCP appointment — no-show"
            else:
                kind, label = "pcp_appointment", "PCP appointment"
            events.append(
                TimelineEvent(
                    at=pcp.appointment_datetime,
                    kind=kind,
                    label=label,
                    detail=pcp.referred_to,
                )
            )
    events.sort(key=lambda e: e.at or "")
    return events


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.get("/episodes/{fin}", response_model=EpisodeDetailResponse)
def get_episode(
    fin: str, user: Dict[str, str] = Depends(get_current_user)
) -> EpisodeDetailResponse:
    as_of, mode = get_as_of()
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT v.patient_id, v.mrn, v.patient_name, v.birth_date, v.sex, v.fin,
                   v.admit_date, v.discharge_date, v.admit_datetime, v.discharge_datetime,
                   v.window_end, v.ms_drg, v.procedure_summary, v.procedure_date,
                   v.discharge_disposition, v.discharge_disposition_code,
                   v.principal_diagnosis, v.length_of_stay_days,
                   e.attending_name,
                   p.emergency_contact_name, p.emergency_contact_relationship,
                   p.emergency_contact_phone
            FROM v_episode v
            JOIN encounter e ON e.fin = v.fin
            JOIN patient p ON p.patient_id = v.patient_id
            WHERE v.fin = ?
            """,
            (fin,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Episode FIN {fin} not found")

        org_name = _org_name(conn, user["org_id"])
        patient_id = row["patient_id"]
        discharge_dt = row["discharge_datetime"]
        # Grace: labs effective up to 24h after discharge still count as "near DC".
        lab_cutoff = None
        if discharge_dt:
            try:
                base = datetime.fromisoformat(discharge_dt)
                lab_cutoff = (base + timedelta(hours=24)).isoformat()
            except ValueError:
                lab_cutoff = discharge_dt

        problems = conn.execute(
            """
            SELECT description, icd10, status
            FROM problem
            WHERE patient_id = ?
              AND (status IS NULL OR lower(status) NOT IN ('resolved', 'inactive'))
            ORDER BY description
            """,
            (patient_id,),
        ).fetchall()

        meds = conn.execute(
            """
            SELECT COALESCE(name_display, name) AS name, sig, route, frequency, indication
            FROM medication
            WHERE fin = ? AND context = 'discharge'
            ORDER BY name
            """,
            (fin,),
        ).fetchall()

        lab_rows = conn.execute(
            """
            SELECT loinc, display, value_num, value_text, unit, abnormal_flag, effective_at
            FROM lab_result
            WHERE fin = ?
              AND (? IS NULL OR effective_at <= ?)
            ORDER BY effective_at DESC
            """,
            (fin, lab_cutoff, lab_cutoff),
        ).fetchall()

        vital_row = conn.execute(
            """
            SELECT recorded_at, temp_f, heart_rate, resp_rate,
                   bp_systolic, bp_diastolic, spo2_percent, o2_delivery, pain_score
            FROM vital
            WHERE fin = ?
              AND (? IS NULL OR recorded_at <= ?)
            ORDER BY recorded_at DESC
            LIMIT 1
            """,
            (fin, discharge_dt, discharge_dt),
        ).fetchone()
        if vital_row is None:
            # Fallback: any vital on the encounter
            vital_row = conn.execute(
                """
                SELECT recorded_at, temp_f, heart_rate, resp_rate,
                       bp_systolic, bp_diastolic, spo2_percent, o2_delivery, pain_score
                FROM vital
                WHERE fin = ?
                ORDER BY recorded_at DESC
                LIMIT 1
                """,
                (fin,),
            ).fetchone()

        therapy_rows = conn.execute(
            """
            SELECT weight_bearing, recommendation, equipment_json, eval_date, discipline
            FROM therapy_evaluation
            WHERE fin = ?
            ORDER BY eval_date
            """,
            (fin,),
        ).fetchall()

        care_team = conn.execute(
            """
            SELECT role, name FROM care_team_member
            WHERE fin = ?
            ORDER BY
              CASE role
                WHEN 'Attending' THEN 0
                WHEN 'Surgeon' THEN 1
                ELSE 2
              END,
              role, name
            """,
            (fin,),
        ).fetchall()

        pcp_row = conn.execute(
            """
            SELECT r.status, r.referred_to, r.appointment_datetime, r.ordered_at,
                   g.pcp_gap
            FROM referral r
            LEFT JOIN v_pcp_gap g ON g.fin = r.fin
            WHERE r.fin = ? AND r.type LIKE '%Primary Care%'
            ORDER BY r.ordered_at DESC
            LIMIT 1
            """,
            (fin,),
        ).fetchone()

        docs = conn.execute(
            """
            SELECT document_type, service_date, author, file_name
            FROM clinical_document
            WHERE fin = ?
            ORDER BY
              CASE document_type
                WHEN 'discharge' THEN 0
                WHEN 'op' THEN 1
                WHEN 'hp' THEN 2
                ELSE 3
              END,
              service_date
            """,
            (fin,),
        ).fetchall()
    finally:
        conn.close()

    status, days_remaining = _classify(
        _parse_date(row["admit_date"]), _parse_date(row["discharge_date"]), as_of
    )

    # Latest key lab per canonical name
    labs_by_name: Dict[str, LabOut] = {}
    for lr in lab_rows:
        canon = _is_key_lab(lr["loinc"], lr["display"])
        if not canon or canon in labs_by_name:
            continue
        labs_by_name[canon] = LabOut(
            display=canon,
            value=_lab_value(lr),
            unit=lr["unit"],
            abnormal_flag=lr["abnormal_flag"] or None,
            effective_at=lr["effective_at"],
        )
    # Stable order: Albumin, Hemoglobin, Creatinine
    labs = [
        labs_by_name[n]
        for n in ("Albumin", "Hemoglobin", "Creatinine")
        if n in labs_by_name
    ]

    weight_bearing = None
    recommendation = None
    equipment: List[str] = []
    therapy_eval_date = None
    for tr in therapy_rows:
        if tr["weight_bearing"] and not weight_bearing:
            weight_bearing = tr["weight_bearing"]
        if tr["recommendation"] and not recommendation:
            recommendation = tr["recommendation"]
        equipment.extend(_parse_equipment(tr["equipment_json"]))
        if tr["eval_date"] and not therapy_eval_date:
            therapy_eval_date = tr["eval_date"]
    # Dedupe equipment preserving order
    seen_eq: set = set()
    equipment_unique: List[str] = []
    for item in equipment:
        if item not in seen_eq:
            seen_eq.add(item)
            equipment_unique.append(item)

    therapy = None
    if weight_bearing or recommendation or equipment_unique or therapy_eval_date:
        therapy = TherapyOut(
            weight_bearing=weight_bearing,
            recommendation=recommendation,
            equipment=equipment_unique,
            eval_date=therapy_eval_date,
        )

    play = _playbook(row["discharge_disposition_code"], row["discharge_disposition"])
    bullets = list(play["bullets"])
    ec_name = row["emergency_contact_name"]
    if ec_name and row["discharge_disposition_code"] in ("01", "06", None):
        rel = row["emergency_contact_relationship"] or "contact"
        bullets = [
            f"Primary outreach: {ec_name} ({rel})",
            *[b for b in bullets if not b.lower().startswith("primary outreach")],
        ]

    pcp: Optional[PcpOut] = None
    if pcp_row:
        gap = bool(pcp_row["pcp_gap"]) if pcp_row["pcp_gap"] is not None else False
        note_parts = []
        if pcp_row["referred_to"]:
            note_parts.append(pcp_row["referred_to"])
        if pcp_row["appointment_datetime"]:
            note_parts.append(f"appt {pcp_row['appointment_datetime'][:10]}")
        pcp = PcpOut(
            status=pcp_row["status"],
            referred_to=pcp_row["referred_to"],
            appointment_datetime=pcp_row["appointment_datetime"],
            ordered_at=pcp_row["ordered_at"],
            gap=gap,
            note=" · ".join(note_parts) if note_parts else None,
        )
    else:
        pcp = PcpOut(
            status=None,
            referred_to=None,
            appointment_datetime=None,
            ordered_at=None,
            gap=True,
            note="No primary care referral on file",
        )

    timeline = _build_timeline(
        admit_dt=row["admit_datetime"] or row["admit_date"],
        procedure_date=row["procedure_date"],
        procedure_summary=row["procedure_summary"],
        therapy_eval_date=therapy_eval_date,
        weight_bearing=weight_bearing,
        discharge_dt=row["discharge_datetime"] or row["discharge_date"],
        disposition=row["discharge_disposition"],
        ms_drg=row["ms_drg"],
        pcp=pcp,
    )

    episode = EpisodeHeader(
        patient_id=patient_id,
        mrn=row["mrn"],
        patient_name=row["patient_name"],
        age=_age_years(_parse_date(row["birth_date"]), as_of),
        sex=row["sex"],
        fin=row["fin"],
        admit_date=row["admit_date"],
        discharge_date=row["discharge_date"],
        admit_datetime=row["admit_datetime"],
        discharge_datetime=row["discharge_datetime"],
        window_end=row["window_end"],
        ms_drg=row["ms_drg"],
        procedure_summary=row["procedure_summary"],
        procedure_date=row["procedure_date"],
        disposition=row["discharge_disposition"],
        disposition_code=row["discharge_disposition_code"],
        principal_diagnosis=row["principal_diagnosis"],
        attending_name=row["attending_name"],
        length_of_stay_days=row["length_of_stay_days"],
        status=status,
        days_remaining=days_remaining,
    )

    return EpisodeDetailResponse(
        meta={
            "as_of": as_of.isoformat(),
            "as_of_mode": mode,
            "org_id": user["org_id"],
            "org_name": org_name,
        },
        episode=episode,
        problems=[
            ProblemOut(
                description=p["description"],
                icd10=p["icd10"],
                status=p["status"],
            )
            for p in problems
        ],
        discharge_meds=[
            MedOut(
                name=m["name"],
                sig=m["sig"],
                route=m["route"],
                frequency=m["frequency"],
                indication=m["indication"],
            )
            for m in meds
        ],
        labs=labs,
        discharge_vitals=(
            VitalsOut(
                recorded_at=vital_row["recorded_at"],
                temp_f=vital_row["temp_f"],
                heart_rate=vital_row["heart_rate"],
                resp_rate=vital_row["resp_rate"],
                bp_systolic=vital_row["bp_systolic"],
                bp_diastolic=vital_row["bp_diastolic"],
                spo2_percent=vital_row["spo2_percent"],
                o2_delivery=vital_row["o2_delivery"],
                pain_score=vital_row["pain_score"],
            )
            if vital_row
            else None
        ),
        therapy=therapy,
        care_team=[CareTeamOut(role=c["role"], name=c["name"]) for c in care_team],
        disposition_context=DispositionContext(
            code=row["discharge_disposition_code"],
            label=row["discharge_disposition"],
            title=play["title"],
            bullets=bullets,
            emergency_contact=EmergencyContact(
                name=row["emergency_contact_name"],
                relationship=row["emergency_contact_relationship"],
                phone=row["emergency_contact_phone"],
            ),
        ),
        pcp=pcp,
        timeline=timeline,
        documents=[
            DocumentOut(
                document_type=d["document_type"],
                service_date=d["service_date"],
                author=d["author"],
                file_name=d["file_name"],
            )
            for d in docs
        ],
    )


@router.get("/episodes/{fin}/documents/{file_name}", response_class=PlainTextResponse)
def get_episode_document(
    fin: str,
    file_name: str,
    user: Dict[str, str] = Depends(get_current_user),
) -> PlainTextResponse:
    """Serve a clinical note for an episode via the patient-data path sandbox."""
    _ = user
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT file_path, file_name
            FROM clinical_document
            WHERE fin = ? AND file_name = ?
            """,
            (fin, file_name),
        ).fetchone()
    finally:
        conn.close()

    if row is None or not row["file_path"]:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        path = safe_patient_file(row["file_path"])
    except SandboxViolation as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    text = path.read_text(encoding="utf-8", errors="replace")
    return PlainTextResponse(
        text,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{row["file_name"]}"'},
    )
