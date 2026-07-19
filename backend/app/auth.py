"""Auth boundary stub (security-foundations §3–4).

Every route depends on get_current_user() so swapping in real SSO later means
changing this one function, not every route. Demo mode returns a fixed
navigator identity scoped to Memorial General.
"""

from __future__ import annotations

from typing import Dict

DEMO_ORG_ID = "260001"  # Memorial General


def get_current_user() -> Dict[str, str]:
    return {
        "id": "demo-navigator",
        "role": "ortho_navigator",
        "org_id": DEMO_ORG_ID,
    }
