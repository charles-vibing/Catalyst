"""Patient app: PT exercise library and logging (A5 / A10).

  GET  /api/patient/exercises           — phase-appropriate exercises + today's logs
  POST /api/patient/exercises/log       — log one exercise
  GET  /api/patient/exercises/adherence — adherence rollup

Exercises come from the static catalog (backend/app/catalog.py, seeded into
app.pt_exercise) and are filtered to the patient's current phase. The episode's
own PT evaluation supplies the weight-bearing order and therapy goals so the
library is framed by what the therapist actually prescribed.

Video URLs are placeholders — no media pipeline in the MVP (TODO.md).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import get_current_patient
from ..db import get_connection
from ..patient_ctx import (
    event_iso,
    load_context,
    now_iso,
    pt_adherence,
    refresh_milestones,
    require_enrollment,
    write_audit,
    write_signal,
)

router = APIRouter(prefix="/api/patient", tags=["patient"])

DIFFICULTY_OPTIONS = ["easy", "ok", "hard", "too_hard"]

# Which catalog phases to show in each episode phase. Home patients never see a
# facility-only set, but home patients early on still benefit from the early
# bed/seated work, so transition_home shows both.
PHASE_EXERCISE_SETS = {
    "inpatient": ["snf"],
    "snf": ["snf"],
    "irf": ["snf"],
    "transition_home": ["snf", "transition_home"],
    "home_recovery": ["transition_home", "home_recovery"],
    "completed": ["home_recovery"],
}


class ExerciseOut(BaseModel):
    code: str
    phase: str
    name: str
    description: Optional[str]
    video_url: Optional[str]
    default_sets: Optional[int]
    default_reps: Optional[int]
    weight_bearing_note: Optional[str]
    logged_today: bool
    sets_done: Optional[int]
    reps_done: Optional[int]
    difficulty: Optional[str]


class ExerciseListResponse(BaseModel):
    meta: Dict[str, Any]
    phase: str
    prescription: Dict[str, Any]
    exercises: List[ExerciseOut]
    adherence: Dict[str, Any]


class LogBody(BaseModel):
    exercise_code: str
    sets_done: Optional[int] = Field(default=None, ge=0, le=20)
    reps_done: Optional[int] = Field(default=None, ge=0, le=100)
    completed: bool = True
    difficulty: Optional[str] = None
    note: Optional[str] = None


class LogResponse(BaseModel):
    logged: Dict[str, Any]
    adherence: Dict[str, Any]
    acknowledgement: str
    milestones_met: List[str]


def _prescription(conn, fin: str) -> Dict[str, Any]:
    """Weight-bearing order, therapy goals, and equipment from the PT/OT eval."""
    rows = conn.execute(
        """
        SELECT discipline, weight_bearing, recommendation, goals_json,
               equipment_json, eval_date, therapist
        FROM therapy_evaluation WHERE fin = ? ORDER BY eval_date
        """,
        (fin,),
    ).fetchall()

    weight_bearing = None
    therapist = None
    goals: List[str] = []
    equipment: List[str] = []
    for r in rows:
        if r["weight_bearing"] and not weight_bearing:
            weight_bearing = r["weight_bearing"]
        if r["therapist"] and not therapist:
            therapist = r["therapist"]
        for field, sink in (("goals_json", goals), ("equipment_json", equipment)):
            raw = r[field]
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    sink.extend(str(x) for x in parsed)
            except (json.JSONDecodeError, TypeError):
                sink.append(str(raw))

    seen: set = set()
    goals_unique = [g for g in goals if not (g in seen or seen.add(g))]
    seen = set()
    equip_unique = [e for e in equipment if not (e in seen or seen.add(e))]

    return {
        "weight_bearing": weight_bearing,
        "therapist": therapist,
        "goals": goals_unique,
        "equipment": equip_unique,
    }


@router.get("/exercises", response_model=ExerciseListResponse)
def list_exercises(
    patient: Dict[str, Any] = Depends(get_current_patient),
) -> ExerciseListResponse:
    conn = get_connection()
    try:
        ctx = load_context(conn, patient)
        require_enrollment(ctx)
        today = ctx["as_of"].isoformat()
        phases = PHASE_EXERCISE_SETS.get(ctx["phase"], ["transition_home"])

        placeholders = ",".join("?" for _ in phases)
        rows = conn.execute(
            f"""
            SELECT e.*, l.sets_done, l.reps_done, l.difficulty, l.completed AS logged
            FROM app.pt_exercise e
            LEFT JOIN app.pt_exercise_log l
              ON l.exercise_code = e.code AND l.fin = ? AND l.log_date = ?
            WHERE e.phase IN ({placeholders})
            ORDER BY e.sort_order
            """,
            (ctx["fin"], today, *phases),
        ).fetchall()

        prescription = _prescription(conn, ctx["fin"])
        adherence = pt_adherence(conn, ctx)
    finally:
        conn.close()

    return ExerciseListResponse(
        meta={"as_of": today, "as_of_mode": ctx["as_of_mode"], "fin": ctx["fin"]},
        phase=ctx["phase"],
        prescription=prescription,
        exercises=[
            ExerciseOut(
                code=r["code"],
                phase=r["phase"],
                name=r["name"],
                description=r["description"],
                video_url=r["video_url"],
                default_sets=r["default_sets"],
                default_reps=r["default_reps"],
                weight_bearing_note=r["weight_bearing_note"],
                logged_today=bool(r["logged"]),
                sets_done=r["sets_done"],
                reps_done=r["reps_done"],
                difficulty=r["difficulty"],
            )
            for r in rows
        ],
        adherence=adherence,
    )


@router.post("/exercises/log", response_model=LogResponse)
def log_exercise(
    body: LogBody, patient: Dict[str, Any] = Depends(get_current_patient)
) -> LogResponse:
    if body.difficulty is not None and body.difficulty not in DIFFICULTY_OPTIONS:
        raise HTTPException(
            status_code=400, detail=f"difficulty must be one of {DIFFICULTY_OPTIONS}"
        )

    conn = get_connection()
    try:
        ctx = load_context(conn, patient)
        require_enrollment(ctx)
        today = ctx["as_of"].isoformat()

        exercise = conn.execute(
            "SELECT code, name, default_sets, default_reps FROM app.pt_exercise WHERE code = ?",
            (body.exercise_code,),
        ).fetchone()
        if exercise is None:
            raise HTTPException(
                status_code=404, detail=f"Unknown exercise {body.exercise_code!r}"
            )

        conn.execute(
            """
            INSERT INTO app.pt_exercise_log (
                patient_id, fin, exercise_code, log_date, sets_done, reps_done,
                completed, difficulty, note, logged_at, org_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fin, exercise_code, log_date) DO UPDATE SET
                sets_done = excluded.sets_done,
                reps_done = excluded.reps_done,
                completed = excluded.completed,
                difficulty = excluded.difficulty,
                note = excluded.note,
                logged_at = excluded.logged_at
            """,
            (
                ctx["patient_id"],
                ctx["fin"],
                body.exercise_code,
                today,
                body.sets_done if body.sets_done is not None else exercise["default_sets"],
                body.reps_done if body.reps_done is not None else exercise["default_reps"],
                int(body.completed),
                body.difficulty,
                body.note,
                event_iso(ctx),
                ctx["org_id"],
            ),
        )

        # "too_hard" is worth a provider's attention but is not an alert on its
        # own — it rides the timeline as a yellow signal.
        severity = "yellow" if body.difficulty == "too_hard" else "green"
        write_signal(
            conn,
            ctx,
            kind="checkin_done",
            severity=severity,
            detail={
                "event": "pt_logged",
                "exercise_code": body.exercise_code,
                "exercise_name": exercise["name"],
                "sets_done": body.sets_done,
                "reps_done": body.reps_done,
                "difficulty": body.difficulty,
            },
            occurred_at=f"{today}T12:30:00+00:00",
        )
        write_audit(
            conn,
            ctx,
            action="pt.log",
            entity_type="pt_exercise_log",
            entity_id=f"{ctx['fin']}:{body.exercise_code}:{today}",
            detail={"difficulty": body.difficulty, "completed": body.completed},
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

        adherence = pt_adherence(conn, ctx)
        logged_today = conn.execute(
            "SELECT COUNT(*) FROM app.pt_exercise_log WHERE fin = ? AND log_date = ? AND completed = 1",
            (ctx["fin"], today),
        ).fetchone()[0]
    finally:
        conn.close()

    if body.difficulty == "too_hard":
        ack = "Logged. We've noted that this one was too hard — your therapist will see it."
    elif logged_today >= 3:
        ack = f"That's {logged_today} exercises today. Nicely done."
    else:
        ack = "Logged."

    return LogResponse(
        logged={
            "exercise_code": body.exercise_code,
            "exercise_name": exercise["name"],
            "log_date": today,
            "completed": body.completed,
            "logged_today_count": logged_today,
        },
        adherence=adherence,
        acknowledgement=ack,
        milestones_met=newly_met,
    )


@router.get("/exercises/adherence")
def get_adherence(patient: Dict[str, Any] = Depends(get_current_patient)) -> Dict[str, Any]:
    conn = get_connection()
    try:
        ctx = load_context(conn, patient)
        require_enrollment(ctx)
        adherence = pt_adherence(conn, ctx)
        by_day = conn.execute(
            """
            SELECT log_date, COUNT(*) AS n
            FROM app.pt_exercise_log WHERE fin = ? AND completed = 1
            GROUP BY log_date ORDER BY log_date DESC LIMIT 30
            """,
            (ctx["fin"],),
        ).fetchall()
    finally:
        conn.close()
    return {
        "meta": {"as_of": ctx["as_of"].isoformat(), "fin": ctx["fin"]},
        "adherence": adherence,
        "by_day": [{"date": r["log_date"], "count": r["n"]} for r in by_day],
    }
