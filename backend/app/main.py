"""Catalyst hospital dashboard API (M1)."""

from __future__ import annotations

import logging
from typing import Dict

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth import get_current_user
from .clock import get_as_of
from .routers import (
    appointment,
    checkin,
    checklist,
    enrollment,
    episode,
    exec_view,
    exercise,
    medications,
    message,
    patient_signals,
    queue,
    redflag,
    roster,
    timeline,
)

logger = logging.getLogger("catalyst")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="Catalyst — SHFFT Episode Command + Patient Companion",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        # Dashboard
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        # Patient companion app
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dashboard surface
app.include_router(roster.router)
app.include_router(episode.router)
app.include_router(queue.router)
app.include_router(patient_signals.router)
app.include_router(exec_view.router)

# Patient companion surface
app.include_router(enrollment.router)
app.include_router(timeline.router)
app.include_router(checkin.router)
app.include_router(redflag.router)
app.include_router(exercise.router)
app.include_router(medications.router)
app.include_router(appointment.router)
app.include_router(message.router)
app.include_router(checklist.router)


@app.on_event("startup")
def startup_banner() -> None:
    as_of, mode = get_as_of()
    logger.warning(
        "=" * 72
        + "\nCATALYST DEMO — SYNTHETIC DATA ONLY."
        + " This is NOT a PHI production deployment: no real patient data,"
        + " no HIPAA/SOC 2 controls. Demo auth stub is active."
        + f"\nAs-of clock: {as_of.isoformat()} ({mode})\n"
        + "=" * 72
    )


@app.get("/api/health")
def health(user: Dict[str, str] = Depends(get_current_user)) -> Dict[str, str]:
    as_of, mode = get_as_of()
    return {"status": "ok", "as_of": as_of.isoformat(), "as_of_mode": mode}
