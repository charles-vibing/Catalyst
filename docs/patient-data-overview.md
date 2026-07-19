# Patient Data Overview

A short guide to how one patient's files are organized in this repo. **Patient 1 (Robert Chen)** is the reference example — other patients follow the same shape with different content.

---

## Where patients live

```
data/patient/
├── 1/          ← patient_id (Catalyst internal; only appears inside JSON files)
├── 2/
├── ...
└── 50/
```

Each folder is one synthetic beneficiary's **hospital data export** — the kind of files Memorial General would have on hand for a TEAM SHFFT episode. There is no application code or pre-computed dashboard metrics in these folders.

---

## Three IDs to know

| ID | Example | Where it appears | What it's for |
|---|---|---|---|
| **patient_id** | `1` | Folder name; `patient_id` field in JSON only | Catalyst's internal row key. **Never** in notes, HL7, or CSV. |
| **MRN** | `10048` | `registration.json`, note headers, HL7 `PID` | Hospital medical record number (patient-level, stable). |
| **FIN** | `004821` | Filenames, encounter records, note headers | Financial / encounter number (episode-level). **This is the main join key** across clinical files. |

Patient 1 also has a second inpatient stay at the anchor hospital with FIN `005102` (pneumonia readmit). Files keyed by FIN exist per encounter.

---

## Patient 1 at a glance

**Story:** 82-year-old man, hip fracture surgery (anchor stay), readmitted day 12 with pneumonia.

| Field | Anchor episode | Readmit |
|---|---|---|
| FIN | `004821` | `005102` |
| Admit | 2026-01-27 | 2026-02-12 |
| Discharge | 2026-01-31 | 2026-02-15 |
| MS-DRG | 481 | 193 |
| Disposition | Home | Home |

---

## Folder layout (patient 1)

```
data/patient/1/
│
├── registration.json              # Demographics, address, PCP, Medicare MBI
├── problem_list.json              # Active problems (patient-level)
├── allergies.json                 # Allergy list (patient-level)
├── social_history.json            # Tobacco, living situation, functional baseline
├── encounter_history.json         # All encounters — start here for timelines
│
├── care_team_004821.json          ┐
├── labs_004821.json               │
├── vitals_004821.json             │  Anchor stay (FIN 004821)
├── vitals_005102.json             │  Readmit vitals (FIN 005102)
├── medications_home_at_admission_004821.json
├── medications_discharge_004821.json
├── nursing_assessment_004821.json
├── orders_inpatient_004821.json
├── pt_ot_eval_004821.json
├── referrals_004821.json
│                                   ┘
├── notes/
│   ├── 004821_hp.txt              # History & physical
│   ├── 004821_op.txt              # Operative note
│   ├── 004821_anesthesia.txt
│   ├── 004821_discharge.txt
│   ├── 004821_rad.txt
│   ├── 005102_hp.txt              # Readmit notes (fewer types)
│   └── 005102_rad.txt
│
├── billing/
│   ├── 004821_837I.json           # Institutional claim (anchor)
│   └── 005102_837I.json           # Institutional claim (readmit)
│
├── feeds/
│   └── medicare_claims_20260510.csv   # Lagged CMS claims (anchor + readmit lines)
│
└── interfaces/hl7/
    ├── MSG202603101630.hl7        # ADT admit (anchor)
    ├── MSG20260314001.hl7         # ADT discharge (anchor)
    └── ...                        # More ADT + ORU lab messages
```

**Naming rule:** encounter-scoped files use `{type}_{FIN}.json` or `notes/{FIN}_{doctype}.txt`. If a patient has no readmit, you won't see a second FIN's files.

---

## File groups (what each is for)

### Patient-level — one per patient, not tied to a single stay

| File | Contents |
|---|---|
| `registration.json` | Name, DOB, sex, address, phones, emergency contact, PCP, Medicare subscriber ID (`SYN-MBI-…`) |
| `problem_list.json` | Chronic/active problems with ICD-10 and SNOMED |
| `allergies.json` | Allergen, reaction, severity |
| `social_history.json` | Tobacco, alcohol, living situation, functional baseline, advance directive |
| `encounter_history.json` | **Manifest of all encounters** — prior hospitalizations, anchor SHFFT stay, readmits. Load this first. |

### Encounter-level — scoped to one FIN (usually the anchor stay)

| File | Contents |
|---|---|
| `labs_{fin}.json` | Lab results (LOINC, value, abnormal flags, timestamps) |
| `vitals_{fin}.json` | Nursing flowsheets (BP, HR, SpO₂, pain, etc.) |
| `medications_home_at_admission_{fin}.json` | Home med list on admission |
| `medications_discharge_{fin}.json` | Discharge med list |
| `nursing_assessment_{fin}.json` | Morse fall scale, Braden, CAM, wound checks |
| `orders_inpatient_{fin}.json` | Inpatient orders (meds, nursing, consults, DME) |
| `pt_ot_eval_{fin}.json` | PT/OT evaluations and disposition recommendations |
| `referrals_{fin}.json` | PCP follow-up referral (status: scheduled, completed, etc.) |
| `care_team_{fin}.json` | Attending, hospitalist, PCP, case manager |

### Clinical documents — plain text, human-readable

| File | Contents |
|---|---|
| `notes/{fin}_hp.txt` | History & physical |
| `notes/{fin}_op.txt` | Operative note |
| `notes/{fin}_anesthesia.txt` | Anesthesia record |
| `notes/{fin}_discharge.txt` | Discharge summary |
| `notes/{fin}_rad.txt` | Radiology report |

Notes reference **MRN and FIN in the header** but not `patient_id`. Body text should match structured data (diagnoses, meds, dates).

### Billing & external feeds

| File | Contents |
|---|---|
| `billing/{fin}_837I.json` | Institutional claim shape: DRG, principal dx, secondary dx with POA, procedures, charges |
| `feeds/medicare_claims_*.csv` | **Lagged payer feed** — can include claims from other hospitals (outside readmits). Join on `BENE_ID` / `FIN`. |
| `feeds/hie_adt_alerts.json` | **Regional HIE ADT notifications** (optional) — thin outside admit/discharge alerts. No clinical notes. Present for some outside-readmit patients only. |

### Interface messages

| File | Contents |
|---|---|
| `interfaces/hl7/*.hl7` | HL7 v2 ADT (admit/discharge) and ORU (results) messages **from Memorial General**. FIN is in the `PV1` segment. |

---

## How files connect

Think of **encounter_history.json** as the spine:

```
registration.json  ──►  patient (MRN 10048)
                              │
encounter_history.json ──►  encounter FIN 004821  (anchor — hip fracture, DRG 481)
                              ├── labs_004821.json
                              ├── vitals_004821.json
                              ├── medications_*_004821.json
                              ├── nursing_assessment_004821.json
                              ├── referrals_004821.json
                              ├── notes/004821_*.txt
                              ├── billing/004821_837I.json
                              └── interfaces/hl7/… (ADT/ORU for this stay)
                              │
                              └── encounter FIN 005102  (readmit — pneumonia, DRG 193)
                                    ├── vitals_005102.json
                                    ├── notes/005102_*.txt
                                    ├── billing/005102_837I.json
                                    └── medicare_claims CSV rows
```

Cross-file consistency matters: discharge disposition, DRG, principal diagnosis, and dates should agree across encounter history, 837I, HL7, and notes.

---

## What varies across the 50-patient cohort

Not every patient has every file. Archetype drives what's present:

| Scenario | What changes |
|---|---|
| No readmit | Only one FIN's clinical files; single 837I |
| SNF bounce-back | Second FIN + readmit notes/claim; admit source = SNF |
| ED-only bounce | Second FIN in encounter history; professional claim line in CSV (`CLM_TYPE = P`) |
| Outside readmit | **No** local chart files. Always a row in `feeds/medicare_claims_*.csv` (competitor CCN `140010`). **Some** patients also have `feeds/hie_adt_alerts.json` (near–real-time ADT ping before claims arrive). Patient 29 is claims-only (no HIE). |
| Active episode | Anchor discharge near the demo date; episode still inside the 30-day window |

See `docs/cohort-tracker.md` (private registry) for the full patient list with archetypes, FINs, and dates.

---

## Relational database (optional)

For SQL-based prototyping, the repo includes:

| Path | Purpose |
|---|---|
| `db/schema.sql` | SQLite table definitions mapped to these files |
| `db/load_cohort.py` | Loads all 50 patients into `db/catalyst.db` |

```bash
python3 db/load_cohort.py
```

Structured data (labs, meds, encounters, claims) lands in tables. Notes and HL7 stay as files; the DB stores a `file_path` pointer in `clinical_document` and `hl7_message`.

---

## Further reading

| Doc | When to use it |
|---|---|
| [design/core-functionality.md](../design/core-functionality.md) | Build checklist for dashboard + patient app |
| [design/mockups/](../design/mockups/) | UI mockups (hospital dashboard) |
| [team-shfft-prototype-features.md](./team-shfft-prototype-features.md) | Full product concept and rationale |
| [shfft-patient-simulation-instructions.md](./shfft-patient-simulation-instructions.md) | Full rules for generating more patients |
| [cohort-tracker.md](./cohort-tracker.md) | Master list of all 50 patients (MRN, FIN, dates, archetypes) |

---

## Quick start for a new developer

1. Open `data/patient/1/registration.json` and `encounter_history.json`.
2. Pick the anchor FIN (`004821`) and read `notes/004821_hp.txt` and `notes/004821_discharge.txt`.
3. Compare structured data: `labs_004821.json`, `nursing_assessment_004821.json`, `billing/004821_837I.json`.
4. Skim `feeds/medicare_claims_20260510.csv` to see how claims tie back to FINs.
5. Run `python3 db/load_cohort.py` and query `SELECT * FROM v_anchor_encounters WHERE mrn = '10048';`

That single patient walkthrough covers ~90% of the patterns in the cohort.
