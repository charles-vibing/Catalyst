"""Catalyst hospital dashboard API (M1)."""

from __future__ import annotations

import logging
from typing import Dict

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth import get_current_user
from .clock import get_as_of
from .routers import episode, queue, roster

logger = logging.getLogger("catalyst")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Catalyst — SHFFT Episode Command", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(roster.router)
app.include_router(episode.router)
app.include_router(queue.router)


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
