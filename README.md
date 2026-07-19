# Catalyst — SHFFT episode command center (MVP)

Hospital dashboard prototype for TEAM SHFFT 30-day post-discharge monitoring
over a **synthetic** 50-patient cohort. Not a PHI production deployment. Design
docs live in [design/](design/); current build is **M1** (read-only roster).

## Runbook

```bash
# 1. Build the database (loads cohort AND applies app tables/views)
python3 db/load_cohort.py

# 2. API on :8000
cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload --port 8000

# 3. Frontend on :5173 (proxies /api → :8000)
cd frontend && npm install && npm run dev
```

Open http://localhost:5173.

## Demo clock

All status / days-remaining math runs against one as-of clock
([design/as-of-date.md](design/as-of-date.md)). Default freeze: `2026-06-28`
(seeded into `app_setting`). Override with env:

```bash
CATALYST_AS_OF=2026-08-01 uvicorn app.main:app --port 8000   # freeze elsewhere
CATALYST_AS_OF= uvicorn app.main:app --port 8000             # empty → live today
```

## Database layout

- `db/schema.sql` — cohort tables, loaded from `data/patient/` by
  `db/load_cohort.py` (rebuilds the DB from scratch each run).
- `db/app_tables.sql` — app-owned tables (`app_setting`, `audit_event`,
  `risk_score`, `signal_event`, `queue_item`, `referral_status_event`) and
  derived views (`v_episode`, `v_roster`, `v_readmit_events`, `v_pcp_gap`).
  Idempotent; applied automatically at the end of `load_cohort.py`, or
  standalone via `python3 db/migrate_app.py`.

## API

- `GET /api/roster` — all SHFFT anchor episodes (MS-DRG 480–482) with
  disposition, computed status (`upcoming`/`active`/`completed`) and days
  remaining in the 30-day window; `meta` carries the resolved as-of date.
- `GET /api/health` — liveness + as-of clock.

Every route resolves a demo user via the `get_current_user()` auth stub, and
patient file reads go through the `data/patient/` path sandbox — see
[design/security-foundations.md](design/security-foundations.md).
