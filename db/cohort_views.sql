-- Catalyst cohort-derived views — applied to db/catalyst.db.
--
-- Split out of db/app_tables.sql when app-owned tables moved to db/app.db:
-- these views read only cohort tables (patient, encounter, referral,
-- hie_adt_alert, medicare_claim_line), so they belong beside those tables in
-- catalyst.db. Keeping every view single-database avoids depending on an
-- ATTACH alias being present at query time.
--
-- Views are DROP + CREATE so definition changes propagate on re-apply;
-- dropping a view destroys no data.
--
-- Applied by db/migrate_app.py (and therefore by db/load_cohort.py).

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

-- Roster payload. Risk tier / open-signal count / readmit + PCP-gap flags join
-- in at the API layer (patient-app engagement fields are added there too,
-- since they live in app.db).
DROP VIEW IF EXISTS v_roster;
CREATE VIEW v_roster AS
SELECT * FROM v_episode;

-- Unified readmission-ish events (D10; minimal shape).
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
-- or never scheduled). Effective-status overrides (app.referral_status_event)
-- layer on in router SQL, not here — that table lives in the other database.
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
