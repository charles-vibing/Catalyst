-- Catalyst app-owned tables — applied to db/app.db (NOT catalyst.db).
--
-- Why a separate database: db/load_cohort.py rebuilds catalyst.db from scratch
-- (it unlinks the file), which used to wipe every app-owned write. Splitting
-- app state into its own file makes "user writes survive a cohort reload" true
-- by construction rather than by convention.
--
-- Access pattern: backend/app/db.py opens catalyst.db as `main` and ATTACHes
-- this file as `app`, so cohort SQL stays unqualified (`FROM v_episode`) and
-- app-owned tables carry an `app.` prefix (`FROM app.queue_item`).
--
-- Two consequences of the split, both deliberate:
--   • SQLite cannot enforce foreign keys across attached databases, so
--     patient_id / fin are SOFT references here. Intra-app.db FKs (e.g.
--     queue_item.signal_event_id) are still real.
--   • No cross-database views. Views live in whichever database holds their
--     tables; joins that span both are written in router SQL. Cohort-derived
--     views (v_episode, v_roster, v_readmit_events, v_pcp_gap) moved to
--     db/cohort_views.sql.
--
-- Idempotent: tables are CREATE TABLE IF NOT EXISTS and are never dropped.
--
-- Apply with:  python3 db/migrate_app.py
-- (load_cohort.py also calls it after every cohort load; it only rebuilds
-- catalyst.db, so applying this file is additive.)

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- App settings (key/value)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS app_setting (
    key     TEXT PRIMARY KEY,
    value   TEXT
);

-- Default demo clock (see design/as-of-date.md). INSERT OR IGNORE so a
-- user/UI override is never clobbered by re-running the migration.
INSERT OR IGNORE INTO app_setting (key, value) VALUES ('as_of_date', '2026-06-28');

-- ---------------------------------------------------------------------------
-- Organizations (hospital / facility tenancy)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS organization (
    org_id       TEXT PRIMARY KEY,               -- CCN, e.g. 260001
    name         TEXT NOT NULL,
    short_name   TEXT,
    city         TEXT,
    state        TEXT,
    is_anchor    INTEGER NOT NULL DEFAULT 0      -- 1 = TEAM accountability hospital
);

INSERT OR IGNORE INTO organization (org_id, name, short_name, city, state, is_anchor)
VALUES
    ('260001', 'Memorial General', 'Memorial', 'Springfield', 'IL', 1),
    ('140010', 'Mercy General', 'Mercy', 'Chicago', 'IL', 0);

-- ---------------------------------------------------------------------------
-- Audit trail (append-only; see design/security-foundations.md §4)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS audit_event (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    at           TEXT NOT NULL DEFAULT (datetime('now')),
    actor_id     TEXT NOT NULL,
    actor_role   TEXT,                           -- ortho_navigator | patient | caregiver
    action       TEXT NOT NULL,                  -- queue.assign, checkin.submit, …
    entity_type  TEXT,
    entity_id    TEXT,
    patient_id   INTEGER,
    org_id       TEXT NOT NULL DEFAULT '260001',
    detail_json  TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_patient ON audit_event(patient_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_event(action, at);

-- ---------------------------------------------------------------------------
-- Dashboard-side app tables (M3–M6)
-- ---------------------------------------------------------------------------

-- M3: cached rule-engine output
CREATE TABLE IF NOT EXISTS risk_score (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id    INTEGER NOT NULL,              -- soft ref → main.patient
    fin           TEXT NOT NULL,
    tier          TEXT,                          -- high | medium | low
    score         INTEGER,
    drivers_json  TEXT,
    computed_at   TEXT,
    org_id        TEXT NOT NULL DEFAULT '260001',
    UNIQUE (fin)
);

-- Patient-app signal stream. Written by the patient app (M5 originally planned
-- to seed these synthetically); one canonical stream the dashboard timeline
-- reads. Every patient action mirrors into here in addition to its own
-- feature table, so D6 has a single ordered source.
CREATE TABLE IF NOT EXISTS signal_event (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id   INTEGER NOT NULL,              -- soft ref → main.patient
    fin          TEXT,
    occurred_at  TEXT NOT NULL,
    kind         TEXT NOT NULL,                  -- checkin_done | checkin_missed | symptom | med_taken | med_missed | help_request
    severity     TEXT,                           -- green | yellow | red
    detail_json  TEXT,
    org_id       TEXT NOT NULL DEFAULT '260001'
);

CREATE INDEX IF NOT EXISTS idx_signal_patient_time ON signal_event(patient_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_signal_fin_time ON signal_event(fin, occurred_at);

-- M6: triage / work queue
CREATE TABLE IF NOT EXISTS queue_item (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    demo_key         TEXT UNIQUE,
    kind             TEXT NOT NULL DEFAULT 'manual', -- app_symptom | app_checkin_missed | app_help_request | pcp_gap | readmit_local | …
    severity         TEXT NOT NULL DEFAULT 'yellow', -- red | yellow
    title            TEXT NOT NULL DEFAULT '',
    summary          TEXT,
    source_type      TEXT,
    source_id        TEXT,
    signal_event_id  INTEGER REFERENCES signal_event(id),
    patient_id       INTEGER NOT NULL,               -- soft ref → main.patient
    fin              TEXT,
    priority         INTEGER,                        -- lower sorts first
    assigned_role    TEXT,
    status           TEXT NOT NULL DEFAULT 'open',   -- open | in_progress | resolved
    resolution_note  TEXT,
    resolution_action TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at      TEXT,
    org_id           TEXT NOT NULL DEFAULT '260001'
);

CREATE INDEX IF NOT EXISTS idx_queue_status ON queue_item(status, priority);
CREATE INDEX IF NOT EXISTS idx_queue_fin ON queue_item(fin, status);

-- M4: dashboard-entered PCP referral status overrides. The patient app also
-- writes here when a patient answers "did you attend?" (source = patient).
CREATE TABLE IF NOT EXISTS referral_status_event (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id   INTEGER NOT NULL,               -- soft ref → main.patient
    fin          TEXT NOT NULL,
    referral_id  INTEGER,                        -- soft ref → main.referral
    status       TEXT NOT NULL,                  -- scheduled | completed | no_show | declined
    noted_at     TEXT NOT NULL DEFAULT (datetime('now')),
    noted_by     TEXT,
    note         TEXT,
    org_id       TEXT NOT NULL DEFAULT '260001'
);

CREATE INDEX IF NOT EXISTS idx_refstatus_fin ON referral_status_event(fin, noted_at);

-- ---------------------------------------------------------------------------
-- Patient companion app tables
-- ---------------------------------------------------------------------------
-- Naming follows the existing app-owned convention: singular snake_case,
-- INTEGER PRIMARY KEY AUTOINCREMENT, ISO-text timestamps, `_json` suffix for
-- JSON payloads, org_id tenancy column, demo_key where a seeder needs an
-- idempotent handle.

-- A1: enrollment. One row per episode; ties the app account to the anchor FIN
-- the dashboard rosters. Confirmed_* fields are what the patient/caregiver
-- verified at onboarding, kept distinct from the EHR-sourced truth so a
-- mismatch is visible to the navigator.
CREATE TABLE IF NOT EXISTS patient_enrollment (
    id                              INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id                      INTEGER NOT NULL,   -- soft ref → main.patient
    fin                             TEXT NOT NULL,      -- soft ref → main.encounter
    relationship                    TEXT NOT NULL DEFAULT 'self',  -- self | caregiver
    confirmed_procedure_type        TEXT,               -- hip | femur
    confirmed_procedure_text        TEXT,
    confirmed_surgeon               TEXT,
    confirmed_discharge_destination TEXT,
    disposition_code                TEXT,
    contact_phone                   TEXT,
    enrolled_at                     TEXT NOT NULL DEFAULT (datetime('now')),
    status                          TEXT NOT NULL DEFAULT 'active', -- active | withdrawn
    org_id                          TEXT NOT NULL DEFAULT '260001',
    UNIQUE (fin)
);

-- A2: milestone-based recovery timeline. Rows are derived per episode on first
-- request (backend/app/phases.py) and then updated as evidence arrives, so the
-- provider sees the same milestone set the patient does.
CREATE TABLE IF NOT EXISTS episode_milestone (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id   INTEGER NOT NULL,
    fin          TEXT NOT NULL,
    code         TEXT NOT NULL,                  -- first_checkin | pt_started | pcp_visit | …
    phase        TEXT NOT NULL,                  -- inpatient | snf | irf | transition_home | home_recovery
    label        TEXT NOT NULL,                  -- patient-facing, outcome-framed
    target_date  TEXT,
    status       TEXT NOT NULL DEFAULT 'pending',-- pending | met | missed
    met_at       TEXT,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    source       TEXT NOT NULL DEFAULT 'derived',-- derived | patient | provider
    org_id       TEXT NOT NULL DEFAULT '260001',
    UNIQUE (fin, code)
);

CREATE INDEX IF NOT EXISTS idx_milestone_fin ON episode_milestone(fin, sort_order);

-- A3: daily check-in. One row per episode per calendar day (upsert on repeat
-- submission the same day).
CREATE TABLE IF NOT EXISTS daily_checkin (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id            INTEGER NOT NULL,
    fin                   TEXT NOT NULL,
    checkin_date          TEXT NOT NULL,          -- ISO date, as-of clock
    pain_score            INTEGER,                -- 0–10
    mood                  TEXT,                   -- good | ok | low | anxious
    sleep_quality         TEXT,                   -- good | fair | poor
    mobility_status       TEXT,                   -- bed | chair | walker | cane | independent
    weight_bearing_status TEXT,                   -- as_instructed | more_than_allowed | less_than_allowed | unsure
    pt_completed          INTEGER,                -- 0/1
    note                  TEXT,
    submitted_at          TEXT NOT NULL DEFAULT (datetime('now')),
    submitted_by          TEXT,                   -- self | caregiver
    org_id                TEXT NOT NULL DEFAULT '260001',
    UNIQUE (fin, checkin_date)
);

CREATE INDEX IF NOT EXISTS idx_checkin_fin_date ON daily_checkin(fin, checkin_date);

-- A4: red-flag symptom triage. One row per structured report; positives fan out
-- to signal_event (timeline) and queue_item (provider alert).
CREATE TABLE IF NOT EXISTS red_flag_report (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id       INTEGER NOT NULL,
    fin              TEXT NOT NULL,
    category         TEXT NOT NULL,               -- fever | dvt | pe | wound | pain | fall
    severity         TEXT NOT NULL,               -- red | yellow | green
    answers_json     TEXT,                        -- structured intake answers
    guidance_code    TEXT,                        -- call_911 | go_to_ed | call_surgeon_now | call_care_team_today | self_care_monitor
    reported_at      TEXT NOT NULL DEFAULT (datetime('now')),
    reported_by      TEXT,                        -- self | caregiver
    signal_event_id  INTEGER REFERENCES signal_event(id),
    queue_item_id    INTEGER REFERENCES queue_item(id),
    org_id           TEXT NOT NULL DEFAULT '260001'
);

CREATE INDEX IF NOT EXISTS idx_redflag_fin_time ON red_flag_report(fin, reported_at);

-- A5: PT exercise catalog (static reference data, seeded from
-- backend/app/catalog.py; not patient-specific).
CREATE TABLE IF NOT EXISTS pt_exercise (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    code               TEXT NOT NULL UNIQUE,
    phase              TEXT NOT NULL,             -- snf | transition_home | home_recovery
    name               TEXT NOT NULL,
    description        TEXT,
    video_url          TEXT,                      -- placeholder for MVP
    default_sets       INTEGER,
    default_reps       INTEGER,
    weight_bearing_note TEXT,
    sort_order         INTEGER NOT NULL DEFAULT 0
);

-- A5: per-session PT logging. Adherence % = logged days / expected days.
CREATE TABLE IF NOT EXISTS pt_exercise_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id     INTEGER NOT NULL,
    fin            TEXT NOT NULL,
    exercise_code  TEXT NOT NULL,                 -- soft ref → pt_exercise.code
    log_date       TEXT NOT NULL,
    sets_done      INTEGER,
    reps_done      INTEGER,
    completed      INTEGER NOT NULL DEFAULT 1,    -- 0/1
    difficulty     TEXT,                          -- easy | ok | hard | too_hard
    note           TEXT,
    logged_at      TEXT NOT NULL DEFAULT (datetime('now')),
    org_id         TEXT NOT NULL DEFAULT '260001',
    UNIQUE (fin, exercise_code, log_date)
);

CREATE INDEX IF NOT EXISTS idx_ptlog_fin_date ON pt_exercise_log(fin, log_date);

-- A6: medication schedule, derived from the cohort's discharge med list.
-- med_class drives the anticoagulation emphasis in the UI.
CREATE TABLE IF NOT EXISTS med_schedule (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id        INTEGER NOT NULL,
    fin               TEXT NOT NULL,
    medication_id     INTEGER,                    -- soft ref → main.medication.id
    name_display      TEXT NOT NULL,
    med_class         TEXT NOT NULL DEFAULT 'other', -- anticoagulant | analgesic | other
    rxnorm            TEXT,
    sig               TEXT,
    frequency_per_day INTEGER NOT NULL DEFAULT 1,
    reminder_time     TEXT,                       -- HH:MM, in-app only for MVP
    active            INTEGER NOT NULL DEFAULT 1,
    org_id            TEXT NOT NULL DEFAULT '260001',
    UNIQUE (fin, name_display)
);

CREATE INDEX IF NOT EXISTS idx_medsched_fin ON med_schedule(fin, active);

-- A6: one row per scheduled dose per day; adherence = taken / (taken+missed).
CREATE TABLE IF NOT EXISTS med_dose_event (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id       INTEGER NOT NULL,
    fin              TEXT NOT NULL,
    med_schedule_id  INTEGER NOT NULL REFERENCES med_schedule(id),
    due_date         TEXT NOT NULL,
    dose_index       INTEGER NOT NULL DEFAULT 0,  -- 0-based within the day
    status           TEXT NOT NULL,               -- taken | missed | skipped
    recorded_at      TEXT NOT NULL DEFAULT (datetime('now')),
    note             TEXT,
    org_id           TEXT NOT NULL DEFAULT '260001',
    UNIQUE (med_schedule_id, due_date, dose_index)
);

CREATE INDEX IF NOT EXISTS idx_meddose_fin_date ON med_dose_event(fin, due_date);

-- A7: appointments. PCP rows seed from main.referral (which carries real
-- appointment_datetime); surgeon / PT / home-health rows are generated because
-- the cohort has no such referrals.
CREATE TABLE IF NOT EXISTS appointment (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id     INTEGER NOT NULL,
    fin            TEXT NOT NULL,
    kind           TEXT NOT NULL,                 -- surgeon | pt | home_health | pcp
    title          TEXT NOT NULL,
    provider_name  TEXT,
    scheduled_at   TEXT,
    location       TEXT,
    source         TEXT NOT NULL DEFAULT 'seeded',-- referral | seeded | patient
    referral_id    INTEGER,                       -- soft ref → main.referral.id
    confirmed      INTEGER NOT NULL DEFAULT 0,
    confirmed_at   TEXT,
    attended       INTEGER,                       -- NULL until answered; 0/1
    attended_at    TEXT,
    org_id         TEXT NOT NULL DEFAULT '260001',
    UNIQUE (fin, kind, scheduled_at)
);

CREATE INDEX IF NOT EXISTS idx_appt_fin_time ON appointment(fin, scheduled_at);

-- A8: secure messaging. Threads surface on the dashboard; unread_* flags let
-- each side badge without scanning messages.
CREATE TABLE IF NOT EXISTS message_thread (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id       INTEGER NOT NULL,
    fin              TEXT NOT NULL,
    subject          TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'open',-- open | closed
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    last_message_at  TEXT,
    unread_provider  INTEGER NOT NULL DEFAULT 0,
    unread_patient   INTEGER NOT NULL DEFAULT 0,
    org_id           TEXT NOT NULL DEFAULT '260001'
);

CREATE INDEX IF NOT EXISTS idx_thread_fin ON message_thread(fin, last_message_at);

CREATE TABLE IF NOT EXISTS message (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id    INTEGER NOT NULL REFERENCES message_thread(id),
    sender_role  TEXT NOT NULL,                   -- patient | caregiver | care_team
    sender_name  TEXT,
    body         TEXT NOT NULL,
    sent_at      TEXT NOT NULL DEFAULT (datetime('now')),
    read_at      TEXT,
    org_id       TEXT NOT NULL DEFAULT '260001'
);

CREATE INDEX IF NOT EXISTS idx_message_thread ON message(thread_id, sent_at);

-- A9: phase-gated checklists — SNF discharge readiness, home safety.
-- Catalog table (static reference, seeded from backend/app/catalog.py).
CREATE TABLE IF NOT EXISTS checklist_item (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    checklist_code TEXT NOT NULL,                 -- snf_discharge_readiness | home_safety
    item_code      TEXT NOT NULL,
    phase          TEXT NOT NULL,                 -- gates visibility in the app
    label          TEXT NOT NULL,
    help_text      TEXT,
    critical       INTEGER NOT NULL DEFAULT 0,    -- 1 = a "no" is provider-visible
    sort_order     INTEGER NOT NULL DEFAULT 0,
    UNIQUE (checklist_code, item_code)
);

CREATE TABLE IF NOT EXISTS checklist_response (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id     INTEGER NOT NULL,
    fin            TEXT NOT NULL,
    checklist_code TEXT NOT NULL,
    item_code      TEXT NOT NULL,
    answer         TEXT NOT NULL,                 -- yes | no | na
    note           TEXT,
    answered_at    TEXT NOT NULL DEFAULT (datetime('now')),
    answered_by    TEXT,
    org_id         TEXT NOT NULL DEFAULT '260001',
    UNIQUE (fin, checklist_code, item_code)
);

CREATE INDEX IF NOT EXISTS idx_checkresp_fin ON checklist_response(fin, checklist_code);
