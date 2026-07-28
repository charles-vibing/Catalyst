# Catalyst — SHFFT episode command center + patient companion (MVP)

Two surfaces over one backend and one **synthetic** 50-patient cohort, for TEAM
SHFFT 30-day post-discharge monitoring. Not a PHI production deployment.

| Surface | Port | Who uses it | What it does |
|---|---|---|---|
| **Hospital dashboard** (`frontend/`) | 5173 | Ortho navigator, case management, SNF liaison | Episode roster, patient episode view, triage queue, patient-app engagement, message inbox |
| **Patient companion** (`patient/`) | 5174 | Patient **or** caregiver (one login, either can use it) | Onboarding, recovery timeline, daily check-in, red-flag triage, PT library, medication tracker, appointments, secure messaging, checklists |

Both read and write the same source of truth, so a check-in submitted in the app
appears on the navigator's screen, and a red flag becomes a triage queue item.

Design docs live in [design/](design/); post-MVP scope is in [TODO.md](TODO.md).

## Runbook

```bash
# 1. Build the databases (cohort + app-owned tables + demo history)
python3 db/load_cohort.py                 # → db/catalyst.db and db/app.db
python3 db/seed_patient_demo.py           # → 30 days of patient-app history

# 2. API on :8000 — serves BOTH surfaces
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000

# 3. Dashboard on :5173
cd frontend && npm install && npm run dev

# 4. Patient app on :5174
cd patient && npm install && npm run dev
```

Then open:

- Dashboard → <http://localhost:5173>
- Patient app → <http://localhost:5174>

Both proxy `/api` to `:8000`.

### Try the two-way flow

1. Open the patient app, sign in as **Okoye, Dennis**, and submit a check-in
   with pain 8/10 — or report a symptom under "Something's wrong".
2. Reload the dashboard. A red `NOW` item appears in the triage queue, the
   roster's **App** column shows the alert count, and the signal timeline under
   "Patient app engagement" shows the event.
3. Reply from the dashboard's **Patient messages** panel; the reply appears in
   the patient app's thread.

Deep links for demos: `http://localhost:5174/?patient=007521&tab=checkin`
(`patient` accepts a FIN, MRN, or patient_id; `tab` is one of `home`, `checkin`,
`exercises`, `meds`, `symptoms`, `appointments`, `messages`, `checklists`).

## Demo clock

All status / phase / days-remaining math runs against one as-of clock
([design/as-of-date.md](design/as-of-date.md)). Default freeze: `2026-06-28`
(seeded into `app_setting`). Patient "today" is this date too, so check-ins land
inside the episode window.

```bash
CATALYST_AS_OF=2026-08-01 uvicorn app.main:app --port 8000   # freeze elsewhere
CATALYST_AS_OF= uvicorn app.main:app --port 8000             # empty → live today
```

Re-run `python3 db/seed_patient_demo.py --reset` after moving the clock so the
seeded history lines up with the new date.

## Demo patients

Three seeded episodes, each a different story:

| Patient | FIN | Story |
|---|---|---|
| **Okoye, Dennis** (p27) | `007521` | **Primary.** Home, hip replacement, on enoxaparin. 14 days of check-ins, 93% engagement, improving pain, PCP visit attended, one resolved fever scare. The "on track" case. |
| Abernathy, Clyde (p25) | `007361` | SNF pathway, 91, caregiver-operated, sparse engagement. Discharge-readiness checklist has two **critical blockers** open — the SNF liaison's problem. |
| Baptiste, Jerome (p29) | `007681` | Early transition home, on warfarin. Missed anticoagulant doses, an **open DVT red flag**, home-safety checklist untouched. The "needs attention today" case. |

## Database layout

Two SQLite files, deliberately separated:

- **`db/catalyst.db`** — cohort tables (`patient`, `encounter`, `lab_result`,
  `medication`, `referral`, `therapy_evaluation`, …) loaded from `data/patient/`
  by `db/load_cohort.py`, plus cohort-derived views from `db/cohort_views.sql`
  (`v_episode`, `v_roster`, `v_readmit_events`, `v_pcp_gap`).
  **The loader deletes and rebuilds this file on every run.**
- **`db/app.db`** — app-owned state from `db/app_tables.sql`: triage queue,
  audit trail, and everything the patient app writes. The loader never touches
  it, so **user and patient data survive a cohort reload by construction**.

`backend/app/db.py` opens `catalyst.db` as `main` and ATTACHes `app.db` as `app`,
so cohort SQL stays unqualified (`FROM v_episode`) and app-owned tables are
prefixed (`FROM app.queue_item`). Two rules follow:

- SQLite can't enforce foreign keys across attached databases, so `patient_id` /
  `fin` are soft references in `app.db`.
- No cross-database views — views live with their tables; joins spanning both
  are written in router SQL.

Override paths with `CATALYST_DB` / `CATALYST_APP_DB`.

### Shared tables the patient app writes

Reused from the existing dashboard schema — the patient app writes these rather
than inventing parallel ones:

| Table | Who writes | Who reads |
|---|---|---|
| `signal_event` | every patient action mirrors here | dashboard signal timeline (D6) |
| `queue_item` | red flags, missed anticoagulant, urgent messages, checklist gaps | existing dashboard triage queue |
| `referral_status_event` | "did you attend?" on a PCP visit → `completed` / `no_show` | dashboard PCP tracker (D8) |
| `audit_event` | every patient write, `actor_role = 'patient'` | audit trail |

New tables: `patient_enrollment`, `episode_milestone`, `daily_checkin`,
`red_flag_report`, `pt_exercise` + `pt_exercise_log`, `med_schedule` +
`med_dose_event`, `appointment`, `message_thread` + `message`,
`checklist_item` + `checklist_response`.

## API

Dashboard routes (`Depends(get_current_user)` — staff):

- `GET /api/roster` — anchor episodes with status, days remaining, and
  patient-app engagement (`enrolled`, `last_checkin_date`, `checkin_adherence`,
  `open_redflags`)
- `GET /api/episodes/{fin}` — episode clinical detail
- `GET /api/episodes/{fin}/signals` — **patient signal timeline (D6)**
- `GET /api/episodes/{fin}/patient-summary` — adherence, latest check-in, red
  flags, checklist gaps, milestones
- `GET /api/queue`, `POST /api/queue/{id}/assign|resolve`
- `GET /api/messages`, `POST /api/messages/{id}/reply|close`

Patient routes (`Depends(get_current_patient)` — all under `/api/patient/`):

`candidates` · `me` · `enrollment` · `timeline` · `checkin/today` ·
`checkin/history` · `checkin` · `redflags/questions` · `redflags` ·
`exercises` · `exercises/log` · `exercises/adherence` · `medications` ·
`medications/dose` · `medications/adherence` · `appointments` ·
`appointments/{id}/confirm|attended` · `messages` · `messages/{id}/read` ·
`checklists` · `checklist/{code}`

Full interactive docs at <http://localhost:8000/docs>.

## Auth

There is **no auth provider** — `backend/app/auth.py` returns two fixed demo
identities, one seam each:

- `get_current_user()` → staff navigator scoped to Memorial General (`260001`)
- `get_current_patient()` → resolves the `X-Catalyst-Patient` header (FIN, MRN,
  or patient_id), falling back to `CATALYST_DEMO_PATIENT`, then to the primary
  demo episode

The patient app's sign-in screen is a patient picker that sets that header. Only
the identifier is kept in the browser, never chart data. Swapping in real SSO
(staff) or a real patient login means changing that one module, not every route
— see [design/security-foundations.md](design/security-foundations.md).

Patient file reads go through the `data/patient/` path sandbox.
