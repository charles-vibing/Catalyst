-- Catalyst app-owned tables + derived views (M1).
--
-- Idempotent by design: safe to re-apply against a live catalyst.db at any
-- time. Tables use CREATE TABLE IF NOT EXISTS (never dropped — user writes
-- such as triage work and audit rows must survive cohort reloads). Views are
-- DROP + CREATE so definition changes propagate; dropping a view destroys no
-- data.
--
-- Apply with:  python3 db/migrate_app.py
--        or :  sqlite3 db/catalyst.db < db/app_tables.sql
-- (load_cohort.py also applies this automatically at the end of a load.)

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- App settings (key/value)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS app_setting (
    key     TEXT PRIMARY KEY,
    value   TEXT
);

-- Default demo clock freeze (see design/as-of-date.md). INSERT OR IGNORE so a
-- user/UI override is never clobbered by re-running the migration.
INSERT OR IGNORE INTO app_setting (key, value) VALUES ('as_of_date', '2026-06-28');

-- ---------------------------------------------------------------------------
-- Organizations (hospital / facility tenancy)
-- ---------------------------------------------------------------------------
-- org_id is the CMS CCN for institutional providers in this demo. App tables
-- already carry org_id; this table is the display/metadata source so the UI
-- never hardcodes "Memorial General".

CREATE TABLE IF NOT EXISTS organization (
    org_id       TEXT PRIMARY KEY,               -- CCN, e.g. 260001
    name         TEXT NOT NULL,                  -- display name
    short_name   TEXT,                           -- optional shorter label
    city         TEXT,
    state        TEXT,
    is_anchor    INTEGER NOT NULL DEFAULT 0       -- 1 = TEAM accountability hospital
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
    actor_role   TEXT,
    action       TEXT NOT NULL,                  -- e.g. queue.assign, pcp.status_update
    entity_type  TEXT,
    entity_id    TEXT,
    patient_id   INTEGER,
    org_id       TEXT NOT NULL DEFAULT '260001',
    detail_json  TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_patient ON audit_event(patient_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_event(action, at);

-- ---------------------------------------------------------------------------
-- App-owned tables for later milestones (M3–M6). Created now so the migration
-- story exists once; all carry org_id per the tenancy seam.
-- ---------------------------------------------------------------------------

-- M3: cached rule-engine output
CREATE TABLE IF NOT EXISTS risk_score (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id    INTEGER NOT NULL REFERENCES patient(patient_id),
    fin           TEXT NOT NULL,
    tier          TEXT,                          -- high | medium | low
    score         INTEGER,
    drivers_json  TEXT,                          -- [{rule, weight, action}, ...]
    computed_at   TEXT,
    org_id        TEXT NOT NULL DEFAULT '260001',
    UNIQUE (fin)
);

-- M5: synthetic patient-app signal stream
CREATE TABLE IF NOT EXISTS signal_event (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id   INTEGER NOT NULL REFERENCES patient(patient_id),
    fin          TEXT,
    occurred_at  TEXT NOT NULL,
    kind         TEXT NOT NULL,                  -- checkin_done | checkin_missed | symptom | med_taken | med_missed | help_request
    severity     TEXT,                           -- green | yellow | red
    detail_json  TEXT,
    org_id       TEXT NOT NULL DEFAULT '260001'
);

CREATE INDEX IF NOT EXISTS idx_signal_patient_time ON signal_event(patient_id, occurred_at);

-- M6: triage / work queue (flexible alert kinds — not signal-only)
CREATE TABLE IF NOT EXISTS queue_item (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    demo_key         TEXT UNIQUE,                    -- stable seed id; NULL for runtime-created
    kind             TEXT NOT NULL DEFAULT 'manual', -- app_symptom | app_checkin_missed | pcp_miss | pcp_gap | readmit_local | readmit_outside | readmit_ed | manual | …
    severity         TEXT NOT NULL DEFAULT 'yellow', -- red | yellow
    title            TEXT NOT NULL DEFAULT '',
    summary          TEXT,
    source_type      TEXT,                           -- signal_event | referral | encounter | hie_adt_alert | medicare_claim_line | …
    source_id        TEXT,
    signal_event_id  INTEGER REFERENCES signal_event(id),
    patient_id       INTEGER NOT NULL REFERENCES patient(patient_id),
    fin              TEXT,
    priority         INTEGER,
    assigned_role    TEXT,
    status           TEXT NOT NULL DEFAULT 'open',   -- open | in_progress | resolved
    resolution_note  TEXT,
    resolution_action TEXT,                          -- call_caregiver | call_patient | mark_resolved | …
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at      TEXT,
    org_id           TEXT NOT NULL DEFAULT '260001'
);

CREATE INDEX IF NOT EXISTS idx_queue_status ON queue_item(status, priority);
CREATE INDEX IF NOT EXISTS idx_queue_fin ON queue_item(fin, status);

-- M4: dashboard-entered PCP referral status overrides
CREATE TABLE IF NOT EXISTS referral_status_event (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id   INTEGER NOT NULL REFERENCES patient(patient_id),
    fin          TEXT NOT NULL,
    referral_id  INTEGER REFERENCES referral(id),
    status       TEXT NOT NULL,                  -- scheduled | completed | no_show | declined
    noted_at     TEXT NOT NULL DEFAULT (datetime('now')),
    noted_by     TEXT,
    note         TEXT,
    org_id       TEXT NOT NULL DEFAULT '260001'
);

CREATE INDEX IF NOT EXISTS idx_refstatus_fin ON referral_status_event(fin, noted_at);

-- ---------------------------------------------------------------------------
-- Views (derived layer). DROP + CREATE keeps definitions current on re-apply.
-- ---------------------------------------------------------------------------

-- One row per SHFFT anchor episode (MS-DRG 480/481/482, anchor FIN 00####).
-- Raw dates are exposed; days-remaining / status are computed in Python
-- against the as-of clock (see backend/app/clock.py).
DROP VIEW IF EXISTS v_episode;
CREATE VIEW v_episode AS
SELECT
    p.patient_id,
    p.mrn,
    p.family_name || ', ' || p.given_name          AS patient_name,
    p.birth_date,
    p.sex,
    e.fin,
    e.admit_datetime,
    e.discharge_datetime,
    date(e.admit_datetime)                         AS admit_date,
    date(e.discharge_datetime)                     AS discharge_date,
    date(e.discharge_datetime, '+30 days')         AS window_end,
    e.ms_drg,
    e.principal_diagnosis,
    e.discharge_disposition_code,
    e.discharge_disposition,
    e.hospital_service,
    e.length_of_stay_days,
    (
        SELECT group_concat(ep.description, '; ')
        FROM encounter_procedure ep
        WHERE ep.fin = e.fin
    )                                              AS procedure_summary,
    (
        SELECT MIN(ep.procedure_date)
        FROM encounter_procedure ep
        WHERE ep.fin = e.fin
    )                                              AS procedure_date
FROM encounter e
JOIN patient p ON p.patient_id = e.patient_id
WHERE e.ms_drg IN ('480', '481', '482')
  AND e.fin GLOB '00[0-9][0-9][0-9][0-9]';

-- Roster payload. For M1 this is v_episode passed through; risk tier /
-- open-signal count / readmit + PCP-gap flags join in at M3–M5.
DROP VIEW IF EXISTS v_roster;
CREATE VIEW v_roster AS
SELECT * FROM v_episode;

-- Unified readmission-ish events (M4 surfaces these; minimal shape now).
DROP VIEW IF EXISTS v_readmit_events;
CREATE VIEW v_readmit_events AS
SELECT
    e.patient_id,
    'local_encounter'                              AS source,
    CASE WHEN e.patient_class = 'Emergency' OR e.ed_visit_datetime IS NOT NULL
         THEN 'ed_only' ELSE 'inpatient' END       AS event_kind,
    COALESCE(date(e.admit_datetime), date(e.ed_visit_datetime)) AS event_date,
    'Memorial General'                             AS facility,
    'real-time'                                    AS latency_label,
    e.fin                                          AS reference,
    e.principal_diagnosis                          AS detail
FROM encounter e
WHERE e.fin NOT GLOB '00[0-9][0-9][0-9][0-9]'
UNION ALL
SELECT
    h.patient_id,
    'hie_adt'                                      AS source,
    h.event_type                                   AS event_kind,
    date(h.event_datetime)                         AS event_date,
    h.sending_facility_name                        AS facility,
    'near-real-time'                               AS latency_label,
    h.alert_id                                     AS reference,
    h.chief_complaint                              AS detail
FROM hie_adt_alert h
UNION ALL
SELECT
    m.patient_id,
    'medicare_claim'                               AS source,
    CASE WHEN m.clm_type = 'P' THEN 'ed_only' ELSE 'inpatient' END AS event_kind,
    m.clm_from_dt                                  AS event_date,
    'CCN ' || COALESCE(m.prvdr_ccn, '?')           AS facility,
    'lagged (received ' || COALESCE(m.file_received_dt, '?') || ')' AS latency_label,
    m.clm_id                                       AS reference,
    m.drg_cd                                       AS detail
FROM medicare_claim_line m
WHERE m.prvdr_ccn IS NOT NULL AND m.prvdr_ccn <> '140010';

-- PCP follow-up per anchor episode; gap flag per D8 heuristic (no referral,
-- or never scheduled). Effective-status overrides layer on at M4.
DROP VIEW IF EXISTS v_pcp_gap;
CREATE VIEW v_pcp_gap AS
SELECT
    v.patient_id,
    v.fin,
    r.status                                       AS referral_status,
    r.appointment_datetime,
    CASE
        WHEN r.id IS NULL THEN 1
        WHEN r.appointment_datetime IS NULL THEN 1
        ELSE 0
    END                                            AS pcp_gap
FROM v_episode v
LEFT JOIN referral r
    ON r.fin = v.fin AND r.type LIKE '%Primary Care%';
