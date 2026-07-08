#!/usr/bin/env python3
"""Load Catalyst patient exports into SQLite (see db/schema.sql)."""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = REPO_ROOT / "data" / "patient"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
DEFAULT_DB = REPO_ROOT / "db" / "catalyst.db"

FIN_RE = re.compile(r"_(\d{6})\.")
NOTE_RE = re.compile(r"^(\d{6})_(\w+)\.txt$")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


def rel_source(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def encounter_id(conn: sqlite3.Connection, fin: str) -> int | None:
    row = conn.execute("SELECT id FROM encounter WHERE fin = ?", (fin,)).fetchone()
    return row["id"] if row else None


def load_patient(conn: sqlite3.Connection, patient_dir: Path) -> None:
    pid = int(patient_dir.name)
    reg_path = patient_dir / "registration.json"
    if not reg_path.exists():
        return

    reg = json.loads(reg_path.read_text(encoding="utf-8"))
    name = reg["name"]
    addr = reg.get("address", {})
    ec = reg.get("emergency_contact", {})
    pcp = reg.get("primary_care_provider", {})
    payer = reg.get("payer_primary", {})

    conn.execute(
        """
        INSERT OR REPLACE INTO patient (
            patient_id, mrn, family_name, given_name, middle_name, birth_date, sex,
            preferred_language, address_line1, address_city, address_state, address_zip,
            phone_home, phone_mobile,
            emergency_contact_name, emergency_contact_relationship, emergency_contact_phone,
            pcp_npi, pcp_name, payer_type, payer_plan, subscriber_id, source_file
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            pid,
            reg["mrn"],
            name["family"],
            name["given"],
            name.get("middle"),
            reg["birth_date"],
            reg["sex"],
            reg.get("preferred_language"),
            addr.get("line1"),
            addr.get("city"),
            addr.get("state"),
            addr.get("zip"),
            reg.get("phone_home"),
            reg.get("phone_mobile"),
            ec.get("name"),
            ec.get("relationship"),
            ec.get("phone"),
            pcp.get("npi"),
            pcp.get("name"),
            payer.get("type"),
            payer.get("plan"),
            payer.get("subscriber_id"),
            rel_source(reg_path),
        ),
    )

    prob_path = patient_dir / "problem_list.json"
    if prob_path.exists():
        conn.execute("DELETE FROM problem WHERE patient_id = ?", (pid,))
        for p in json.loads(prob_path.read_text())["problems"]:
            conn.execute(
                """
                INSERT INTO problem (
                    patient_id, problem_id, description, icd10, snomed, status,
                    onset_date, last_reviewed, source_file
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    pid,
                    p.get("problem_id"),
                    p["description"],
                    p.get("icd10"),
                    p.get("snomed"),
                    p.get("status"),
                    p.get("onset_date"),
                    p.get("last_reviewed"),
                    rel_source(prob_path),
                ),
            )

    allergy_path = patient_dir / "allergies.json"
    if allergy_path.exists():
        conn.execute("DELETE FROM allergy WHERE patient_id = ?", (pid,))
        data = json.loads(allergy_path.read_text())
        for a in data.get("allergies", []):
            conn.execute(
                """
                INSERT INTO allergy (patient_id, allergen, reaction, severity, verified, source_file)
                VALUES (?,?,?,?,?,?)
                """,
                (
                    pid,
                    a["allergen"],
                    a.get("reaction"),
                    a.get("severity"),
                    1 if a.get("verified") else 0,
                    rel_source(allergy_path),
                ),
            )

    social_path = patient_dir / "social_history.json"
    if social_path.exists():
        s = json.loads(social_path.read_text())
        t = s.get("tobacco", {})
        conn.execute(
            """
            INSERT OR REPLACE INTO social_history (
                patient_id, tobacco_status, tobacco_pack_years, tobacco_quit_date,
                alcohol, substance_use, living_situation, functional_baseline,
                advance_directive, primary_language, interpreter_needed,
                source_file, extracted_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                pid,
                t.get("status"),
                t.get("pack_years"),
                t.get("quit_date"),
                s.get("alcohol"),
                s.get("substance_use"),
                s.get("living_situation"),
                s.get("functional_baseline"),
                s.get("advance_directive"),
                s.get("primary_language"),
                1 if s.get("interpreter_needed") else 0,
                rel_source(social_path),
                s.get("extracted_at"),
            ),
        )

    enc_path = patient_dir / "encounter_history.json"
    if enc_path.exists():
        data = json.loads(enc_path.read_text())
        for e in data.get("encounters", []):
            fin = e["fin"]
            conn.execute(
                """
                INSERT OR REPLACE INTO encounter (
                    patient_id, fin, admit_datetime, discharge_datetime, ed_visit_datetime,
                    patient_class, hospital_service, admit_source,
                    discharge_disposition_code, discharge_disposition,
                    attending_npi, attending_name,
                    principal_diagnosis_icd10, principal_diagnosis,
                    ms_drg, length_of_stay_days, source_file, extracted_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    pid,
                    fin,
                    e.get("admit_datetime"),
                    e.get("discharge_datetime"),
                    e.get("ed_visit_datetime"),
                    e.get("patient_class"),
                    e.get("hospital_service"),
                    e.get("admit_source"),
                    e.get("discharge_disposition_code"),
                    e.get("discharge_disposition"),
                    e.get("attending_npi"),
                    e.get("attending"),
                    e.get("principal_diagnosis_icd10"),
                    e.get("principal_diagnosis"),
                    e.get("ms_drg"),
                    e.get("length_of_stay_days"),
                    rel_source(enc_path),
                    data.get("extracted_at"),
                ),
            )
            eid = encounter_id(conn, fin)
            conn.execute("DELETE FROM encounter_procedure WHERE fin = ?", (fin,))
            for proc in e.get("procedures", []):
                conn.execute(
                    """
                    INSERT INTO encounter_procedure (
                        encounter_id, fin, procedure_date, description, icd10_pcs, cpt
                    ) VALUES (?,?,?,?,?,?)
                    """,
                    (
                        eid,
                        fin,
                        proc.get("date"),
                        proc.get("description"),
                        proc.get("icd10_pcs"),
                        proc.get("cpt"),
                    ),
                )

    for path in sorted(patient_dir.glob("labs_*.json")):
        fin = FIN_RE.search(path.name).group(1)
        data = json.loads(path.read_text())
        conn.execute("DELETE FROM lab_result WHERE fin = ? AND source_file = ?", (fin, rel_source(path)))
        eid = encounter_id(conn, fin)
        for r in data.get("results", []):
            val = r.get("value")
            conn.execute(
                """
                INSERT INTO lab_result (
                    patient_id, encounter_id, fin, loinc, display,
                    value_num, value_text, unit, effective_at,
                    abnormal_flag, reference_range, source_file
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    pid,
                    eid,
                    fin,
                    r.get("loinc"),
                    r["display"],
                    val if isinstance(val, (int, float)) else None,
                    None if isinstance(val, (int, float)) else str(val) if val is not None else None,
                    r.get("unit"),
                    r["effective_at"],
                    r.get("abnormal_flag"),
                    r.get("reference_range"),
                    rel_source(path),
                ),
            )

    for path in sorted(patient_dir.glob("vitals_*.json")):
        fin = FIN_RE.search(path.name).group(1)
        data = json.loads(path.read_text())
        conn.execute("DELETE FROM vital WHERE fin = ? AND source_file = ?", (fin, rel_source(path)))
        eid = encounter_id(conn, fin)
        for v in data.get("vitals", []):
            conn.execute(
                """
                INSERT INTO vital (
                    patient_id, encounter_id, fin, recorded_at,
                    temp_f, heart_rate, resp_rate, bp_systolic, bp_diastolic,
                    spo2_percent, o2_delivery, pain_score, source_file
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    pid,
                    eid,
                    fin,
                    v["recorded_at"],
                    v.get("temp_f"),
                    v.get("heart_rate"),
                    v.get("resp_rate"),
                    v.get("bp_systolic"),
                    v.get("bp_diastolic"),
                    v.get("spo2_percent"),
                    v.get("o2_delivery"),
                    v.get("pain_score"),
                    rel_source(path),
                ),
            )

    for path in sorted(patient_dir.glob("medications_*_*.json")):
        fin = FIN_RE.search(path.name).group(1)
        context = "home_at_admission" if "home_at_admission" in path.name else "discharge"
        data = json.loads(path.read_text())
        conn.execute(
            "DELETE FROM medication WHERE fin = ? AND context = ?",
            (fin, context),
        )
        eid = encounter_id(conn, fin)
        for m in data.get("medications", []):
            conn.execute(
                """
                INSERT INTO medication (
                    patient_id, encounter_id, fin, context, med_id, name, name_display,
                    rxnorm, sig, route, frequency, start_date, end_date,
                    status, indication, prescriber, source_file
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    pid,
                    eid,
                    fin,
                    context,
                    m.get("med_id"),
                    m["name"],
                    m.get("name_display"),
                    m.get("rxnorm"),
                    m.get("sig"),
                    m.get("route"),
                    m.get("frequency"),
                    m.get("start_date"),
                    m.get("end_date"),
                    m.get("status"),
                    m.get("indication"),
                    m.get("prescriber"),
                    rel_source(path),
                ),
            )

    for path in sorted(patient_dir.glob("orders_inpatient_*.json")):
        fin = FIN_RE.search(path.name).group(1)
        data = json.loads(path.read_text())
        conn.execute("DELETE FROM inpatient_order WHERE fin = ?", (fin,))
        eid = encounter_id(conn, fin)
        for o in data.get("orders", []):
            conn.execute(
                """
                INSERT INTO inpatient_order (
                    patient_id, encounter_id, fin, order_id, category,
                    description, status, ordered_at, ordered_by, source_file
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    pid,
                    eid,
                    fin,
                    o.get("order_id"),
                    o.get("category"),
                    o["description"],
                    o.get("status"),
                    o.get("ordered_at"),
                    o.get("ordered_by"),
                    rel_source(path),
                ),
            )

    for path in sorted(patient_dir.glob("referrals_*.json")):
        fin = FIN_RE.search(path.name).group(1)
        data = json.loads(path.read_text())
        conn.execute("DELETE FROM referral WHERE fin = ?", (fin,))
        eid = encounter_id(conn, fin)
        for r in data.get("referrals", []):
            conn.execute(
                """
                INSERT INTO referral (
                    patient_id, encounter_id, fin, referral_id, type,
                    referred_to_npi, referred_to, reason, priority, status,
                    ordered_at, ordered_by, appointment_datetime, source_file
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    pid,
                    eid,
                    fin,
                    r.get("referral_id"),
                    r.get("type"),
                    r.get("referred_to_npi"),
                    r.get("referred_to"),
                    r.get("reason"),
                    r.get("priority"),
                    r.get("status"),
                    r.get("ordered_at"),
                    r.get("ordered_by"),
                    r.get("appointment_datetime"),
                    rel_source(path),
                ),
            )

    for path in sorted(patient_dir.glob("care_team_*.json")):
        fin = FIN_RE.search(path.name).group(1)
        data = json.loads(path.read_text())
        conn.execute("DELETE FROM care_team_member WHERE fin = ?", (fin,))
        eid = encounter_id(conn, fin)
        for m in data.get("members", []):
            conn.execute(
                """
                INSERT INTO care_team_member (
                    patient_id, encounter_id, fin, role, name, npi, service, source_file
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    pid,
                    eid,
                    fin,
                    m["role"],
                    m["name"],
                    m.get("npi"),
                    m.get("service"),
                    rel_source(path),
                ),
            )

    for path in sorted(patient_dir.glob("nursing_assessment_*.json")):
        fin = FIN_RE.search(path.name).group(1)
        data = json.loads(path.read_text())
        conn.execute("DELETE FROM nursing_assessment WHERE fin = ?", (fin,))
        eid = encounter_id(conn, fin)
        for a in data.get("assessments", []):
            conn.execute(
                """
                INSERT INTO nursing_assessment (
                    patient_id, encounter_id, fin, assessment, recorded_at,
                    score, risk_level, positive, site, status, factors_json, source_file
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    pid,
                    eid,
                    fin,
                    a["assessment"],
                    a["recorded_at"],
                    a.get("score"),
                    a.get("risk_level"),
                    1 if a.get("positive") else 0 if "positive" in a else None,
                    a.get("site"),
                    a.get("status"),
                    json.dumps(a.get("factors")) if a.get("factors") else None,
                    rel_source(path),
                ),
            )

    for path in sorted(patient_dir.glob("pt_ot_eval_*.json")):
        fin = FIN_RE.search(path.name).group(1)
        data = json.loads(path.read_text())
        conn.execute("DELETE FROM therapy_evaluation WHERE fin = ?", (fin,))
        eid = encounter_id(conn, fin)
        pt = data.get("physical_therapy")
        if pt:
            conn.execute(
                """
                INSERT INTO therapy_evaluation (
                    patient_id, encounter_id, fin, discipline, eval_date, therapist,
                    prior_function, current_mobility, weight_bearing, stairs,
                    recommendation, goals_json, source_file, extracted_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    pid,
                    eid,
                    fin,
                    "PT",
                    pt.get("eval_date"),
                    pt.get("therapist"),
                    pt.get("prior_function"),
                    pt.get("current_mobility"),
                    pt.get("weight_bearing"),
                    pt.get("stairs"),
                    pt.get("recommendation"),
                    json.dumps(pt.get("goals")) if pt.get("goals") else None,
                    rel_source(path),
                    data.get("extracted_at"),
                ),
            )
        ot = data.get("occupational_therapy")
        if ot:
            conn.execute(
                """
                INSERT INTO therapy_evaluation (
                    patient_id, encounter_id, fin, discipline, eval_date, therapist,
                    adl_status, home_safety, equipment_json, source_file, extracted_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    pid,
                    eid,
                    fin,
                    "OT",
                    ot.get("eval_date"),
                    ot.get("therapist"),
                    ot.get("adl_status"),
                    ot.get("home_safety"),
                    json.dumps(ot.get("equipment_recommended"))
                    if ot.get("equipment_recommended")
                    else None,
                    rel_source(path),
                    data.get("extracted_at"),
                ),
            )

    billing_dir = patient_dir / "billing"
    if billing_dir.exists():
        for path in sorted(billing_dir.glob("*_837I.json")):
            fin = path.stem.split("_")[0]
            claim = json.loads(path.read_text())
            conn.execute("DELETE FROM claim_diagnosis WHERE fin = ?", (fin,))
            conn.execute("DELETE FROM claim_procedure WHERE fin = ?", (fin,))
            conn.execute("DELETE FROM institutional_claim WHERE fin = ?", (fin,))
            eid = encounter_id(conn, fin)
            conn.execute(
                """
                INSERT INTO institutional_claim (
                    patient_id, encounter_id, fin, claim_number, form_type, bill_type,
                    facility_ccn, admit_date, discharge_date, discharge_hour,
                    discharge_status, ms_drg, attending_npi, principal_diagnosis,
                    total_charges, statement_from, statement_to, payer, subscriber_id,
                    submitted_date, raw_json, source_file
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    pid,
                    eid,
                    fin,
                    claim.get("claim_number"),
                    claim.get("form_type", "837I"),
                    claim.get("bill_type"),
                    claim.get("facility_ccn"),
                    claim.get("admit_date"),
                    claim.get("discharge_date"),
                    claim.get("discharge_hour"),
                    claim.get("discharge_status"),
                    claim.get("ms_drg"),
                    claim.get("attending_npi"),
                    claim.get("principal_diagnosis"),
                    claim.get("total_charges"),
                    claim.get("statement_from"),
                    claim.get("statement_to"),
                    claim.get("payer"),
                    claim.get("subscriber_id"),
                    claim.get("submitted_date"),
                    path.read_text(encoding="utf-8"),
                    rel_source(path),
                ),
            )
            claim_row_id = conn.execute(
                "SELECT id FROM institutional_claim WHERE fin = ? AND claim_number = ?",
                (fin, claim.get("claim_number")),
            ).fetchone()["id"]
            for i, dx in enumerate(claim.get("other_diagnoses", []), start=1):
                conn.execute(
                    """
                    INSERT INTO claim_diagnosis (claim_id, fin, seq, code, poa)
                    VALUES (?,?,?,?,?)
                    """,
                    (claim_row_id, fin, i, dx["code"], dx.get("poa")),
                )
            for proc in claim.get("procedure_codes", []):
                conn.execute(
                    """
                    INSERT INTO claim_procedure (claim_id, fin, code, procedure_date)
                    VALUES (?,?,?,?)
                    """,
                    (claim_row_id, fin, proc["code"], proc.get("date")),
                )

    feeds_dir = patient_dir / "feeds"
    if feeds_dir.exists():
        for path in sorted(feeds_dir.glob("medicare_claims_*.csv")):
            with path.open(encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    clm_id = row["CLM_ID"]
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO medicare_claim_line (
                            patient_id, bene_id, clm_id, fin, clm_from_dt, clm_thru_dt,
                            prvdr_ccn, prvdr_npi, clm_type, drg_cd, hcpcs_cd,
                            line_pmt_amt, pos_cd, file_received_dt, source_file
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            pid,
                            row["BENE_ID"],
                            clm_id,
                            row.get("FIN") or None,
                            row.get("CLM_FROM_DT"),
                            row.get("CLM_THRU_DT"),
                            row.get("PRVDR_CCN") or None,
                            row.get("PRVDR_NPI") or None,
                            row.get("CLM_TYPE"),
                            row.get("DRG_CD") or None,
                            row.get("HCPCS_CD") or None,
                            float(row["LINE_PMT_AMT"]) if row.get("LINE_PMT_AMT") else None,
                            row.get("POS_CD") or None,
                            row.get("FILE_RECEIVED_DT"),
                            rel_source(path),
                        ),
                    )

    notes_dir = patient_dir / "notes"
    if notes_dir.exists():
        for path in sorted(notes_dir.glob("*.txt")):
            m = NOTE_RE.match(path.name)
            if not m:
                continue
            fin, doc_type = m.group(1), m.group(2)
            text = path.read_text(encoding="utf-8")
            eid = encounter_id(conn, fin)
            conn.execute(
                """
                INSERT OR REPLACE INTO clinical_document (
                    patient_id, encounter_id, fin, document_type,
                    file_path, file_name, char_count, source_file
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    pid,
                    eid,
                    fin,
                    doc_type,
                    rel_source(path),
                    path.name,
                    len(text),
                    rel_source(path),
                ),
            )

    hl7_dir = patient_dir / "interfaces" / "hl7"
    if hl7_dir.exists():
        for path in sorted(hl7_dir.glob("*.hl7")):
            text = path.read_text(encoding="utf-8")
            fin = None
            msg_type = None
            control_id = None
            msg_dt = None
            for line in text.splitlines():
                if line.startswith("MSH|"):
                    parts = line.split("|")
                    if len(parts) > 8:
                        msg_type = parts[8]
                    if len(parts) > 9:
                        control_id = parts[9]
                    if len(parts) > 6:
                        msg_dt = parts[6]
                if line.startswith("PV1|") and fin is None:
                    fields = line.split("|")
                    if len(fields) > 19 and fields[19]:
                        fin = fields[19]
            eid = encounter_id(conn, fin) if fin else None
            conn.execute(
                """
                INSERT OR REPLACE INTO hl7_message (
                    patient_id, encounter_id, fin, message_type, control_id,
                    message_datetime, file_path, file_name, source_file
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    pid,
                    eid,
                    fin,
                    msg_type,
                    control_id,
                    msg_dt,
                    rel_source(path),
                    path.name,
                    rel_source(path),
                ),
            )


def load_cohort(db_path: Path = DEFAULT_DB) -> None:
    if db_path.exists():
        db_path.unlink()
    conn = connect(db_path)
    try:
        for patient_dir in sorted(
            (p for p in DATA_ROOT.iterdir() if p.is_dir() and p.name.isdigit()),
            key=lambda p: int(p.name),
        ):
            load_patient(conn, patient_dir)
        conn.commit()
        counts = {
            row[0]: row[1]
            for row in conn.execute(
                """
                SELECT 'patients', COUNT(*) FROM patient
                UNION ALL SELECT 'encounters', COUNT(*) FROM encounter
                UNION ALL SELECT 'lab_results', COUNT(*) FROM lab_result
                UNION ALL SELECT 'documents', COUNT(*) FROM clinical_document
                UNION ALL SELECT 'medicare_lines', COUNT(*) FROM medicare_claim_line
                """
            )
        }
        print(f"Loaded {db_path}")
        for k, v in counts.items():
            print(f"  {k}: {v}")
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Load patient exports into SQLite")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Output SQLite path")
    args = parser.parse_args()
    load_cohort(args.db)
