"""Auth boundary stubs (security-foundations §3–4).

Two identities, one seam each. Every route depends on one of these so swapping
in real SSO (staff) or a real patient login later means changing this module,
not every route.

There is no auth provider in this prototype — no sessions, tokens, password
store, or user table. Both functions return demo identities:

  get_current_user()    → staff (ortho navigator) for the dashboard
  get_current_patient() → patient/caregiver for the companion app

Patient resolution order (first match wins):
  1. X-Catalyst-Patient header — patient_id, MRN, or anchor FIN
  2. CATALYST_DEMO_PATIENT env
  3. DEFAULT_DEMO_PATIENT_FIN below

The patient app sends the header after the demo patient picker, which stands in
for a login. Per security-foundations §5 only that identifier is kept in the
browser (a "future login token" is the sanctioned exception) — never chart data.

MVP is deliberately login-agnostic: one account per episode, used by the patient
OR a caregiver, distinguished only by patient_enrollment.relationship. Separate
caregiver accounts are post-MVP (see TODO.md).
"""

from __future__ import annotations

import os
from typing import Dict, Optional

from fastapi import Header, HTTPException

from .db import get_connection

DEMO_ORG_ID = "260001"  # Memorial General

# Primary demo episode: p27 Okoye, Dennis — discharged home 2026-06-14, DRG 481
# hip replacement, anticoagulated, PCP visit already past at the frozen as-of
# date. See db/seed_patient_demo.py.
DEFAULT_DEMO_PATIENT_FIN = "007521"


def get_current_user() -> Dict[str, str]:
    """Staff identity for dashboard routes."""
    return {
        "id": "demo-navigator",
        "role": "ortho_navigator",
        "org_id": DEMO_ORG_ID,
    }


def _lookup_episode(token: Optional[str]) -> Optional[Dict[str, object]]:
    """Resolve a patient_id / MRN / FIN to an anchor episode row."""
    conn = get_connection()
    try:
        if token:
            row = conn.execute(
                """
                SELECT patient_id, mrn, fin, patient_name
                FROM v_episode
                WHERE fin = ? OR mrn = ? OR patient_id = ?
                ORDER BY discharge_date DESC
                LIMIT 1
                """,
                (token, token, token if str(token).isdigit() else -1),
            ).fetchone()
            if row is not None:
                return dict(row)
            return None
        row = conn.execute(
            """
            SELECT patient_id, mrn, fin, patient_name
            FROM v_episode WHERE fin = ?
            """,
            (DEFAULT_DEMO_PATIENT_FIN,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_current_patient(
    x_catalyst_patient: Optional[str] = Header(default=None),
) -> Dict[str, object]:
    """Patient/caregiver identity for companion-app routes.

    Raises 404 when the supplied identifier matches no anchor episode, so a
    stale browser identifier surfaces as a clean error instead of silently
    falling back to a different patient's chart.
    """
    token = x_catalyst_patient or os.environ.get("CATALYST_DEMO_PATIENT") or None
    episode = _lookup_episode(token)
    if episode is None:
        raise HTTPException(
            status_code=404,
            detail=f"No SHFFT episode found for patient identifier {token!r}",
        )
    return {
        "id": f"patient-{episode['patient_id']}",
        "role": "patient",
        "org_id": DEMO_ORG_ID,
        "patient_id": episode["patient_id"],
        "fin": episode["fin"],
        "mrn": episode["mrn"],
        "patient_name": episode["patient_name"],
    }
