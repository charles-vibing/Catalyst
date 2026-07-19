-- Catalyst SHFFT synthetic cohort — SQLite schema
-- Maps file exports under data/patient/{patient_id}/ to relational tables.
--
-- Design:
--   • Structured clinical facts → tables
--   • Note narrative + raw HL7 → files on disk, indexed via clinical_document / hl7_message
--   • patient_id is Catalyst-internal (from JSON only); mrn + fin are hospital natural keys
--
-- File → table quick reference:
--   registration.json              → patient
--   problem_list.json                → problem
--   allergies.json                   → allergy
--   social_history.json              → social_history
--   encounter_history.json           → encounter, encounter_procedure
--   labs_{fin}.json                  → lab_result
--   vitals_{fin}.json                → vital
--   medications_home_at_admission_*  → medication (context = home_at_admission)
--   medications_discharge_*          → medication (context = discharge)
--   orders_inpatient_{fin}.json      → inpatient_order
--   referrals_{fin}.json             → referral
--   care_team_{fin}.json             → care_team_member
--   nursing_assessment_{fin}.json    → nursing_assessment
--   pt_ot_eval_{fin}.json            → therapy_evaluation
--   billing/{fin}_837I.json          → institutional_claim, claim_diagnosis, claim_procedure
--   feeds/medicare_claims_*.csv      → medicare_claim_line
--   feeds/hie_adt_alerts.json        → hie_adt_alert (outside ADT notifications)
--   notes/{fin}_{type}.txt           → clinical_document (file_path pointer)
--   interfaces/hl7/*.hl7             → hl7_message (file_path pointer)

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Patient-level (longitudinal)
-- ---------------------------------------------------------------------------

CREATE TABLE patient (
    patient_id          INTEGER PRIMARY KEY,          -- Catalyst internal; from registration.json
    mrn                 TEXT NOT NULL UNIQUE,
    family_name         TEXT NOT NULL,
    given_name          TEXT NOT NULL,
    middle_name         TEXT,
    birth_date          TEXT NOT NULL,                -- ISO date
    sex                 TEXT NOT NULL,
    preferred_language  TEXT,
    address_line1       TEXT,
    address_city        TEXT,
    address_state       TEXT,
    address_zip         TEXT,
    phone_home          TEXT,
    phone_mobile        TEXT,
    emergency_contact_name         TEXT,
    emergency_contact_relationship TEXT,
    emergency_contact_phone        TEXT,
    pcp_npi             TEXT,
    pcp_name            TEXT,
    payer_type          TEXT,
    payer_plan          TEXT,
    subscriber_id       TEXT,                         -- MBI: SYN-MBI-######
    source_file         TEXT,
    extracted_at        TEXT
);

CREATE TABLE problem (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id      INTEGER NOT NULL REFERENCES patient(patient_id),
    problem_id      INTEGER,                          -- source problem_id when present
    description     TEXT NOT NULL,
    icd10           TEXT,
    snomed          TEXT,
    status          TEXT,
    onset_date      TEXT,
    last_reviewed   TEXT,
    source_file     TEXT,
    UNIQUE (patient_id, problem_id)
);

CREATE TABLE allergy (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id      INTEGER NOT NULL REFERENCES patient(patient_id),
    allergen        TEXT NOT NULL,
    reaction        TEXT,
    severity        TEXT,
    verified        INTEGER,                          -- 0/1
    source_file     TEXT
);

CREATE TABLE social_history (
    patient_id              INTEGER PRIMARY KEY REFERENCES patient(patient_id),
    tobacco_status          TEXT,
    tobacco_pack_years      REAL,
    tobacco_quit_date       TEXT,
    alcohol                 TEXT,
    substance_use           TEXT,
    living_situation        TEXT,
    functional_baseline     TEXT,
    advance_directive       TEXT,
    primary_language        TEXT,
    interpreter_needed      INTEGER,                  -- 0/1
    source_file             TEXT,
    extracted_at            TEXT
);

-- ---------------------------------------------------------------------------
-- Encounters (FIN is the hospital-wide join key)
-- ---------------------------------------------------------------------------

CREATE TABLE encounter (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id                  INTEGER NOT NULL REFERENCES patient(patient_id),
    fin                         TEXT NOT NULL,
    admit_datetime              TEXT,
    discharge_datetime          TEXT,
    ed_visit_datetime           TEXT,                 -- ED-only / bounce cases
    patient_class               TEXT,                 -- Inpatient, Emergency, ...
    hospital_service            TEXT,
    admit_source                TEXT,
    discharge_disposition_code  TEXT,
    discharge_disposition       TEXT,
    attending_npi               TEXT,
    attending_name              TEXT,
    principal_diagnosis_icd10   TEXT,
    principal_diagnosis         TEXT,
    ms_drg                      TEXT,
    length_of_stay_days         INTEGER,
    source_file                 TEXT,
    extracted_at                TEXT,
    UNIQUE (fin)
);

CREATE TABLE encounter_procedure (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    encounter_id    INTEGER NOT NULL REFERENCES encounter(id),
    fin             TEXT NOT NULL,
    procedure_date  TEXT,
    description     TEXT,
    icd10_pcs       TEXT,
    cpt             TEXT
);

-- ---------------------------------------------------------------------------
-- Encounter-scoped clinical (one row per observation / line item)
-- ---------------------------------------------------------------------------

CREATE TABLE lab_result (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id      INTEGER NOT NULL REFERENCES patient(patient_id),
    encounter_id    INTEGER REFERENCES encounter(id),
    fin             TEXT NOT NULL,
    loinc           TEXT,
    display         TEXT NOT NULL,
    value_num       REAL,
    value_text      TEXT,                             -- when value is non-numeric
    unit            TEXT,
    effective_at    TEXT NOT NULL,
    abnormal_flag   TEXT,
    reference_range TEXT,
    source_file     TEXT
);

CREATE TABLE vital (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id      INTEGER NOT NULL REFERENCES patient(patient_id),
    encounter_id    INTEGER REFERENCES encounter(id),
    fin             TEXT NOT NULL,
    recorded_at     TEXT NOT NULL,
    temp_f          REAL,
    heart_rate      INTEGER,
    resp_rate       INTEGER,
    bp_systolic     INTEGER,
    bp_diastolic    INTEGER,
    spo2_percent    INTEGER,
    o2_delivery     TEXT,
    pain_score      INTEGER,
    source_file     TEXT
);

CREATE TABLE medication (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id      INTEGER NOT NULL REFERENCES patient(patient_id),
    encounter_id    INTEGER REFERENCES encounter(id),
    fin             TEXT NOT NULL,
    context         TEXT NOT NULL,                    -- home_at_admission | discharge
    med_id          TEXT,
    name            TEXT NOT NULL,
    name_display    TEXT,
    rxnorm          TEXT,
    sig             TEXT,
    route           TEXT,
    frequency       TEXT,
    start_date      TEXT,
    end_date        TEXT,
    status          TEXT,
    indication      TEXT,
    prescriber      TEXT,
    source_file     TEXT
);

CREATE TABLE inpatient_order (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id      INTEGER NOT NULL REFERENCES patient(patient_id),
    encounter_id    INTEGER REFERENCES encounter(id),
    fin             TEXT NOT NULL,
    order_id        TEXT,
    category        TEXT,
    description     TEXT NOT NULL,
    status          TEXT,
    ordered_at      TEXT,
    ordered_by      TEXT,
    source_file     TEXT
);

CREATE TABLE referral (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id              INTEGER NOT NULL REFERENCES patient(patient_id),
    encounter_id            INTEGER REFERENCES encounter(id),
    fin                     TEXT NOT NULL,
    referral_id             TEXT,
    type                    TEXT,
    referred_to_npi         TEXT,
    referred_to             TEXT,
    reason                  TEXT,
    priority                TEXT,
    status                  TEXT,
    ordered_at              TEXT,
    ordered_by              TEXT,
    appointment_datetime    TEXT,
    source_file             TEXT
);

CREATE TABLE care_team_member (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id      INTEGER NOT NULL REFERENCES patient(patient_id),
    encounter_id    INTEGER REFERENCES encounter(id),
    fin             TEXT NOT NULL,
    role            TEXT NOT NULL,
    name            TEXT NOT NULL,
    npi             TEXT,
    service         TEXT,
    source_file     TEXT
);

CREATE TABLE nursing_assessment (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id      INTEGER NOT NULL REFERENCES patient(patient_id),
    encounter_id    INTEGER REFERENCES encounter(id),
    fin             TEXT NOT NULL,
    assessment      TEXT NOT NULL,                    -- Morse Fall Scale, Braden, CAM, ...
    recorded_at     TEXT NOT NULL,
    score           INTEGER,
    risk_level      TEXT,
    positive        INTEGER,                          -- CAM: 0/1
    site            TEXT,                             -- wound assessments
    status          TEXT,
    factors_json    TEXT,                           -- JSON array of factor strings
    source_file     TEXT
);

CREATE TABLE therapy_evaluation (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id          INTEGER NOT NULL REFERENCES patient(patient_id),
    encounter_id        INTEGER REFERENCES encounter(id),
    fin                 TEXT NOT NULL,
    discipline          TEXT NOT NULL,                -- PT | OT
    eval_date           TEXT,
    therapist           TEXT,
    prior_function      TEXT,
    current_mobility    TEXT,
    weight_bearing      TEXT,
    stairs              TEXT,
    recommendation      TEXT,
    adl_status          TEXT,
    home_safety         TEXT,
    goals_json          TEXT,
    equipment_json      TEXT,
    source_file         TEXT,
    extracted_at        TEXT
);

-- ---------------------------------------------------------------------------
-- Billing / payer feeds
-- ---------------------------------------------------------------------------

CREATE TABLE institutional_claim (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id          INTEGER NOT NULL REFERENCES patient(patient_id),
    encounter_id        INTEGER REFERENCES encounter(id),
    fin                 TEXT NOT NULL,
    claim_number        TEXT,
    form_type           TEXT DEFAULT '837I',
    bill_type           TEXT,
    facility_ccn        TEXT,
    admit_date          TEXT,                         -- YYYYMMDD in source
    discharge_date      TEXT,
    discharge_hour      TEXT,
    discharge_status    TEXT,
    ms_drg              TEXT,
    attending_npi       TEXT,
    principal_diagnosis TEXT,
    total_charges       REAL,
    statement_from      TEXT,
    statement_to        TEXT,
    payer               TEXT,
    subscriber_id       TEXT,
    submitted_date      TEXT,
    raw_json            TEXT,                         -- optional full 837I payload
    source_file         TEXT,
    UNIQUE (fin, claim_number)
);

CREATE TABLE claim_diagnosis (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id        INTEGER NOT NULL REFERENCES institutional_claim(id),
    fin             TEXT NOT NULL,
    seq             INTEGER,
    code            TEXT NOT NULL,
    poa             TEXT
);

CREATE TABLE claim_procedure (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id        INTEGER NOT NULL REFERENCES institutional_claim(id),
    fin             TEXT NOT NULL,
    code            TEXT NOT NULL,
    procedure_date  TEXT
);

-- Medicare claims feed (may include outside-hospital rows)
CREATE TABLE medicare_claim_line (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id          INTEGER REFERENCES patient(patient_id),
    bene_id             TEXT NOT NULL,
    clm_id              TEXT NOT NULL,
    fin                 TEXT,
    clm_from_dt         TEXT,
    clm_thru_dt         TEXT,
    prvdr_ccn           TEXT,
    prvdr_npi           TEXT,
    clm_type            TEXT,                         -- I = institutional, P = professional
    drg_cd              TEXT,
    hcpcs_cd            TEXT,
    line_pmt_amt        REAL,
    pos_cd              TEXT,
    file_received_dt    TEXT,
    source_file         TEXT,
    UNIQUE (clm_id)
);

-- ---------------------------------------------------------------------------
-- Document / interface artifacts (metadata in DB, payload on disk)
-- ---------------------------------------------------------------------------

CREATE TABLE clinical_document (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id      INTEGER NOT NULL REFERENCES patient(patient_id),
    encounter_id    INTEGER REFERENCES encounter(id),
    fin             TEXT NOT NULL,
    document_type   TEXT NOT NULL,                    -- hp, op, discharge, anesthesia, rad
    file_path       TEXT NOT NULL UNIQUE,             -- relative to repo root or patient dir
    file_name       TEXT NOT NULL,
    char_count      INTEGER,
    service_date    TEXT,                             -- parsed from note header when available
    author          TEXT,
    source_file     TEXT
);

CREATE TABLE hl7_message (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id      INTEGER REFERENCES patient(patient_id),
    encounter_id    INTEGER REFERENCES encounter(id),
    fin             TEXT,
    message_type    TEXT,                             -- ADT^A01, ADT^A03, ORU^R01, ...
    control_id      TEXT,
    message_datetime TEXT,
    file_path       TEXT NOT NULL UNIQUE,
    file_name       TEXT NOT NULL,
    source_file     TEXT
);

-- ---------------------------------------------------------------------------
-- Indexes (SHFFT roster, episode timeline, risk queries)
-- ---------------------------------------------------------------------------

CREATE INDEX idx_encounter_patient_admit ON encounter(patient_id, admit_datetime);
CREATE INDEX idx_encounter_drg ON encounter(ms_drg);
CREATE INDEX idx_encounter_disposition ON encounter(discharge_disposition_code);

CREATE INDEX idx_lab_fin ON lab_result(fin);
CREATE INDEX idx_lab_loinc ON lab_result(loinc, effective_at);

CREATE INDEX idx_vital_fin_recorded ON vital(fin, recorded_at);

CREATE INDEX idx_medication_fin_context ON medication(fin, context);

CREATE INDEX idx_referral_fin_status ON referral(fin, status);

CREATE INDEX idx_nursing_fin_assessment ON nursing_assessment(fin, assessment);

CREATE INDEX idx_medicare_bene ON medicare_claim_line(bene_id);
CREATE INDEX idx_medicare_fin ON medicare_claim_line(fin);
CREATE INDEX idx_medicare_ccn ON medicare_claim_line(prvdr_ccn);

-- Regional HIE ADT notifications (outside facilities; thin payload)
CREATE TABLE hie_adt_alert (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id                  INTEGER NOT NULL REFERENCES patient(patient_id),
    alert_id                    TEXT NOT NULL UNIQUE,
    event_type                  TEXT NOT NULL,            -- A01, A03, ...
    event_label                 TEXT,
    event_datetime              TEXT NOT NULL,
    received_at                 TEXT NOT NULL,
    sending_facility_name       TEXT,
    sending_facility_ccn        TEXT,
    patient_class               TEXT,
    visit_number                TEXT,                     -- outside FIN / visit #
    hospital_service            TEXT,
    chief_complaint             TEXT,
    discharge_disposition       TEXT,
    admit_source                TEXT,
    matched_on_json             TEXT,
    anchor_episode_fin          TEXT,
    days_after_anchor_discharge INTEGER,
    hie_name                    TEXT,
    source_file                 TEXT
);

CREATE INDEX idx_hie_patient ON hie_adt_alert(patient_id);
CREATE INDEX idx_hie_ccn ON hie_adt_alert(sending_facility_ccn);
CREATE INDEX idx_hie_anchor ON hie_adt_alert(anchor_episode_fin);

CREATE INDEX idx_document_fin_type ON clinical_document(fin, document_type);

CREATE INDEX idx_hl7_fin ON hl7_message(fin);

-- ---------------------------------------------------------------------------
-- Example views
-- ---------------------------------------------------------------------------

-- Anchor SHFFT episodes: hip fracture DRG family, anchor FIN range
CREATE VIEW v_anchor_encounters AS
SELECT
    p.patient_id,
    p.mrn,
    p.family_name || ', ' || p.given_name AS patient_name,
    e.fin,
    e.admit_datetime,
    e.discharge_datetime,
    e.ms_drg,
    e.discharge_disposition_code,
    e.discharge_disposition,
    e.hospital_service
FROM encounter e
JOIN patient p ON p.patient_id = e.patient_id
WHERE e.ms_drg IN ('480', '481', '482')
  AND e.fin GLOB '00[0-9][0-9][0-9][0-9]';

-- PCP follow-up referral status per anchor episode
CREATE VIEW v_pcp_referrals AS
SELECT
    e.fin,
    p.mrn,
    r.status,
    r.appointment_datetime,
    r.ordered_at
FROM referral r
JOIN encounter e ON e.fin = r.fin
JOIN patient p ON p.patient_id = r.patient_id
WHERE r.type LIKE '%Primary Care%';
