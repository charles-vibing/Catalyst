"""Single demo clock (design/as-of-date.md).

Resolution order:
  1. env CATALYST_AS_OF — non-empty value freezes the clock to that date;
     present-but-empty explicitly selects live today()
  2. app_setting.as_of_date (seeded to 2026-06-28 by db/app_tables.sql)
  3. live date.today()

No other module should call date.today() for business logic.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Tuple

from .db import get_setting

ENV_VAR = "CATALYST_AS_OF"


def get_as_of() -> Tuple[date, str]:
    """Return (as_of_date, mode) where mode is 'frozen' or 'live'."""
    env = os.environ.get(ENV_VAR)
    if env is not None:
        env = env.strip()
        if env:
            return date.fromisoformat(env), "frozen"
        return date.today(), "live"

    setting = get_setting("as_of_date")
    if setting:
        return date.fromisoformat(setting), "frozen"
    return date.today(), "live"
