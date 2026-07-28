# Post-MVP TODO

Things deliberately **not** built in the patient companion app MVP, plus gaps
found while building it. Nothing here blocks the demo.

## Explicitly excluded from this MVP (by instruction)

### Caregiver mode
The MVP is login-agnostic: one account per episode, used by the patient or a
caregiver, distinguished only by `patient_enrollment.relationship`. Not built:

- Separate caregiver accounts with their own credentials
- Multiple caregivers linked to one episode, with per-person permissions
- Caregiver-specific notifications ("Dad missed his check-in")
- A proxy audit distinction finer than `actor_role`, so it is currently not
  possible to prove *which* caregiver answered
- `core-functionality.md` A6 treats caregiver proxy as first-class; this MVP
  treats it as a flag

### Accessibility beyond framework defaults
The app uses larger base type (17px), 48px tap targets, semantic buttons, and
`aria-pressed` on choice controls — but that came from designing for an
80-year-old on a phone, not from an accessibility pass. Not done:

- Screen-reader audit; no NVDA/VoiceOver testing
- Focus-trap and keyboard-navigation review of the tab shell
- WCAG contrast verification (the palette is inherited from the dashboard and
  was never formally checked)
- Reduced-motion, text-scaling, and high-contrast modes
- Language support: `patient.preferred_language` and
  `social_history.interpreter_needed` exist in the cohort and are **ignored** —
  the app is English-only

### Notifications infrastructure
In-app only, as instructed. `med_schedule.reminder_time` is stored and rendered
as a due-time chip; `appointment.due_soon` is computed against the as-of clock.
Nothing is sent. Not built:

- Push, SMS, email, or IVR delivery
- A scheduler/worker to fire reminders (there is no background job runner at all)
- Escalation ladders for missed check-ins — note the `checkin_missed` signal kind
  is written by the seeder but **nothing generates it at runtime**, because that
  needs a scheduled job
- Notification preferences, quiet hours, delivery receipts
- Consent/opt-in flows for SMS (`security-foundations.md` §6 defers these)

### Offline support
The app assumes connectivity. Not built: service worker, request queue and
replay, optimistic writes with reconciliation, conflict resolution for a
check-in submitted twice from two devices.

## Gaps found while building

### Data model
- **No `Surgeon` role in the cohort.** `care_team_member` has PCP, Case Manager,
  Attending, and Hospitalist consult. The app uses the orthopaedic attending as
  the surgeon proxy. `backend/app/routers/episode.py:502` sorts on a `'Surgeon'`
  role that never matches — dead branch, left alone.
- **Disposition labels are inconsistent** — five spellings of home-health
  ("Home with home health agency (HHA)", "Home w/ HHA", …). Both surfaces
  normalise by substring. A real fix is a lookup table keyed on
  `discharge_disposition_code`.
- **Medication names are free text** with brand names inline and 12 spellings of
  enoxaparin. `patient_ctx.classify_med()` is substring matching; a real
  implementation would resolve RxNorm.
- **Dose frequency is parsed from prose** (`_frequency_per_day` in
  `routers/medications.py`) and defaults to once daily. PRN meds are modelled as
  scheduled, which overstates the adherence denominator for pain medication.
- **Post-acute length of stay is a guess.** `phases.POST_ACUTE_DAYS` assumes 14
  days for SNF / 12 for IRF because the cohort has no facility discharge event.
  A patient can therefore be modelled as "home" while still at the facility —
  which is why checklist gating is disposition-aware, not purely phase-aware.
- **No referral rows for surgeon or PT visits.** Those appointments are
  generated at fixed offsets (14 and 3 days post-discharge).

### Not built on the dashboard side
D6 (patient signal timeline) was built because the patient app needed somewhere
to write. Still unimplemented from `design/hospital-dashboard-mvp-plan.md`:

- **D2 / D5** risk engine — `risk_score` exists and is empty; no rule module
- **D3** filter/sort by risk tier and PCP gap (status and engagement sort work)
- **D8** PCP tracker UI — `referral_status_event` is now *written* by the patient
  app, but no dashboard screen reads or edits it
- **D10** readmission visibility — `v_readmit_events` is a view with no endpoint
- **D11–D14** compliance strip, outreach audit trail, population KPIs
- `POST /api/queue/{id}/assign` now has a client function
  (`assignQueueItem`) but still no UI control that calls it

### Testing
**There are no tests anywhere in this repo** — no pytest, no vitest, no fixtures.
Everything was verified by driving the running app and the API by hand. Highest
value first:

1. `rules.evaluate()` — every category × severity path. Pure function, no I/O,
   and it decides whether a patient is told to call 911.
2. `phases.resolve_phase()` / `milestone_template()` — boundary dates.
3. `patient_ctx` adherence maths — the denominators are easy to get wrong and
   both surfaces report them.
4. Route-level tests over a temp DB pair for the write fan-out (does a red flag
   really produce a `queue_item`?).

### Known rough edges
- `refresh_milestones` is called on a GET (`/patient/timeline` and
  `/patient-summary`). Idempotent, but a write during a read; a scheduled
  recompute would be cleaner.
- A met milestone never reverts, by design. If a patient regresses from cane to
  walker, "Getting around with a cane" stays met.
- `red_flag_report.answers_json` carries `_title` / `_reasons` alongside the raw
  answers. Convenient, but it mixes input with derived output in one column.
- The patient app's `styles.css` duplicates the dashboard's `:root` token block.
  Deliberate — there is no shared package and adding one would have meant a build
  step. If a third surface appears, extract the tokens.
- No pagination anywhere. `/signals` caps at 500 rows; a full 30-day episode with
  five medications already generates ~200.
