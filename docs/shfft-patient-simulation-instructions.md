# SHFFT / TEAM Synthetic Patient Simulation Instructions

Instructions for generating synthetic hospital patient data for the Catalyst SHFFT/TEAM prototype (patients 2 through ~15). Follow this document exactly — the goal is a cohort that looks like real hospital data exports, is internally consistent, and exercises every dashboard feature described in [team-shfft-prototype-features.md](./team-shfft-prototype-features.md).

**Companion docs:**
- [expected-data-sources-and-formats.md](./expected-data-sources-and-formats.md) — what each data source is and why it exists
- [team-shfft-prototype-features.md](./team-shfft-prototype-features.md) — the product these patients must exercise

---

## 1. Purpose and scope

We are simulating what a **single anchor hospital** (Memorial General Hospital, CCN `260001`) would actually have on hand for patients in **TEAM SHFFT episodes**:

- **TEAM** = CMS Transforming Episode Accountability Model. The hospital is accountable for Medicare FFS spend and quality from anchor admission through **30 days after anchor discharge**.
- **SHFFT** = Surgical Hip and Femur Fracture Treatment. Inpatient-only episodes, **MS-DRG 480, 481, or 482**, **Traditional Medicare (FFS) only**.

Each synthetic patient is a folder of files that mimic **hospital data exports** — EHR extracts (JSON), clinical notes (TXT), HL7 v2 interface messages, institutional claims (837I-shaped JSON), and a lagged CMS claims feed (CSV). There is **no app data and no derived data** in these folders — risk scores, episode day counters, and engagement metrics are computed by the Catalyst product, never stored in `data/`.

Scope of this document: how to generate patients `2..N` so that the cohort supports a credible dashboard demo (episode roster, risk stratification, readmission detection, PCP referral tracking, claims-lag storytelling).

---

## 2. Patient 1 is the template

`data/patient/1/` is the **gold-standard reference**. Robert Chen, 82M: multimorbid (HFrEF, COPD, HTN, T2DM, CKD 3a, afib on apixaban, osteoporosis), mechanical fall → displaced right intertrochanteric femur fracture → hemiarthroplasty (MS-DRG 481) → discharged home with daughter → **readmitted to the anchor hospital on post-discharge day 12 with pneumonia** (MS-DRG 193, inside the 30-day episode).

When generating a new patient:

1. **Copy patient 1's file set and schemas exactly.** Same file names (with the new FIN substituted), same JSON keys, same note section headers, same HL7 segment structure. Do not invent new schemas or add fields.
2. **Change the content, not the shape.** New demographics, story, codes, values, timestamps.
3. **Prune to fit the archetype.** A patient with no readmission has no second-FIN files. A patient with fewer comorbidities has a shorter problem list and med list. Every patient still gets the full anchor-stay file set (Section 6).

Before generating your first patient, read **all** of patient 1's files end to end. The cross-file relationships (Section 9) are the hard part, and patient 1 demonstrates almost all of them.

---

## 3. SHFFT / TEAM requirements checklist

Every synthetic patient MUST satisfy all of the following to be a valid SHFFT episode:

### Episode eligibility (non-negotiable)

- [ ] **Payer:** Traditional Medicare FFS (`payer_primary.type = "Medicare"`, plan `"Medicare Part A/B"`). Never Medicare Advantage, commercial, or Medicaid-primary.
- [ ] **Age:** 65+ at admission (typical SHFFT range 68–92; skew 75+).
- [ ] **Anchor stay:** one inpatient encounter at Memorial General with a hip/femur fracture principal diagnosis (`S72.*` with 7th character `A`) and an operative procedure.
- [ ] **MS-DRG on the anchor claim:** exactly `480` (w/ MCC), `481` (w/ CC), or `482` (w/o CC/MCC) — and the secondary diagnosis list must plausibly justify it (Section 10).
- [ ] **Episode window:** anchor discharge date + 30 days. All post-discharge events for this patient land inside (or deliberately just outside) this window.

### TEAM process artifacts (the compliance story)

- [ ] **TEAM beneficiary notification** (`team_beneficiary_notification_{FIN}.txt`) — dated on or before discharge, with acknowledgment section filled in.
- [ ] **PCP referral at discharge** (`referrals_{FIN}.json` + a matching `Referral` order in `orders_inpatient_{FIN}.json`) — TEAM requires it. Vary the status across the cohort: scheduled, completed, patient declined, never scheduled (a gap the dashboard should surface).
- [ ] **Discharge disposition** consistent across all files (Section 9) — this drives the disposition-aware features.

### Clinical data the risk score needs (make sure these exist and tell the story)

- [ ] Fracture type + laterality (intertrochanteric / femoral neck / subtrochanteric / shaft).
- [ ] Procedure type (hemiarthroplasty vs ORIF vs IM nail) with ICD-10-PCS + CPT.
- [ ] Time from ED arrival to surgery (SHFFT urgency: usually 24–48h; delay >48h is itself a risk flag).
- [ ] ASA class in the anesthesia note (II–IV; correlate with comorbidity burden).
- [ ] Pre-op labs: **albumin, hemoglobin, creatinine** at minimum (known SHFFT readmission predictors). Low albumin/anemia for high-risk patients; normal for low-risk.
- [ ] Nursing assessments: Morse Fall Scale, Braden, CAM. High-risk patients get high Morse scores and/or a positive CAM (delirium).
- [ ] Comorbidity burden in `problem_list.json` that matches the notes, the claim's secondary diagnoses, and the med list.
- [ ] Functional baseline + living situation in `social_history.json` (lives alone vs with caregiver — a top risk driver).
- [ ] PT/OT eval with weight-bearing status and disposition recommendation that matches the actual disposition.
- [ ] DME orders (walker etc.) for home discharges.

---

## 4. Patient archetype matrix

Generate the cohort from this matrix. Patient 1 already exists (row 0). Assign one archetype per patient; the archetype label goes in your **private cohort tracker only** (Section 5) — **never in any data file**.

| # | Archetype | Clinical story | MS-DRG | Risk | Readmit? | Disposition | Key data to emphasize |
|---|---|---|---|---|---|---|---|
| 0 | *(exists — patient 1)* Multimorbid, anchor readmission | 82M, HFrEF/COPD/CKD/afib, intertroch fx, hemiarthroplasty; pneumonia readmit day 12 | 481 | High | **Y** (anchor, day 12) | Home (01) | Full reference implementation |
| 1 | Healthy, smooth recovery | 72F, only HTN + osteopenia, ground-level fall, femoral neck fx, hemiarthroplasty; uneventful; PCP visit completed day 6 | 482 | Low | N | Home (01) | Normal labs, low Morse, ASA II, completed PCP referral — the "green" roster row |
| 2 | Complex medical → SNF | 85F, HFrEF + T2DM + AKI on CKD during stay (MCC), intertroch fx, IM nail; slow PT progress | 480 | High | N | SNF (03) | MCC diagnosis (e.g. `N17.9` AKI, not POA), long LOS (7d), PT note recommending SNF, SNF name in discharge note |
| 3 | Frail, lives alone, delirium | 88F, dementia + osteoporosis, femoral neck fx, hemiarthroplasty; post-op delirium (CAM+); UTI/delirium readmit day 8 | 481 | High | **Y** (anchor, day 8) | Home w/ HHA (06) | Positive CAM, lives alone in social history, HHA referral, short readmit stay (2–3d) |
| 4 | Invisible outside readmission | 79M, COPD + HTN, intertroch fx, ORIF; readmitted to **competitor hospital** day 15 (CHF exacerbation) — anchor hospital has **no encounter/notes/HL7** for it; appears **only** in the lagged Medicare claims CSV | 481 | Medium | **Y** (outside, day 15) | Home (01) | Claims-lag storytelling: outside institutional claim line with a non-`260001` CCN, `FILE_RECEIVED_DT` ~45 days after service |
| 5 | SNF → bounce-back | 86M, T2DM + PVD + CKD, subtrochanteric fx, IM nail; SNF discharge; aspiration pneumonia readmit from SNF day 6 | 480 | High | **Y** (anchor, day 6, admit source "Skilled Nursing Facility") | SNF (03) | Readmit H&P references SNF; admit source differs from patient 1's ED pattern |
| 6 | ED-only bounce, no readmission | 77F, afib on warfarin, intertroch fx, hemiarthroplasty; wound drainage scare → anchor ED visit day 10, evaluated and discharged same day | 481 | Medium | N (ED visit only) | Home (01) | ED-only encounter: `patient_class: "Emergency"` in encounter_history, professional claim line (`P...`, HCPCS 99284/99285) in feeds, **no** inpatient 837I for it |
| 7 | IRF disposition | 74M, Parkinson's disease + HTN, femoral shaft fx, IM nail; good rehab candidate | 481 | Medium | N | IRF (62) | Disposition code 62 everywhere; PT note recommending inpatient rehab; Parkinson's in problem list and med list (carbidopa-levodopa) |
| 8 | Delayed surgery, weekend discharge | 81M, afib on warfarin (INR 2.8 at admission), intertroch fx; surgery delayed to hour ~60 for INR reversal; discharged Saturday; PCP referral placed but **never scheduled**; late readmit day 25 (GI bleed) | 481 | Med-High | **Y** (anchor, day 25) | Home (01) | Process-risk signals: time-to-surgery >48h, weekend discharge, open referral status, INR labs |
| 9 | Social risk, missed follow-up | 76F, dual-eligible flag via Medicaid secondary, lives alone 3rd-floor walkup, minimal comorbidities, femoral neck fx, hemiarthroplasty; PCP appointment no-showed | 482 | Medium | N | Home w/ HHA (06) | Social history is the story: transport barriers, no caregiver; referral status "Scheduled" then appointment date in the past with no completion |
| 10 | Very old, minimal chart | 91F, only HTN + osteoporosis documented (thin problem list — realistic for patients seen elsewhere), intertroch fx, hemiarthroplasty | 482 | Med-High (age alone) | N | SNF (03) | Sparse data as a feature: short problem list, few home meds, age ≥90 driving risk despite clean chart |

Optional advanced rows if the cohort goes beyond 12 patients:

| # | Archetype | Notes |
|---|---|---|
| 11 | Second smooth home recovery | Clone of archetype 1 with different demographics/fracture — dashboards need more than one green row |
| 12 | Episode still in progress | Anchor discharge ~10 days before the demo "as of" date; no post-discharge events yet — an **active** episode with days remaining |
| 13 | Hospice / episode edge case | Discharged to hospice (disposition 50/51) — exercise episode-status handling; keep only one of these |

**Cohort balance requirements** (whatever subset you generate):

- Readmit rate 25–35% of cohort (enriched vs the real-world 8–15% so the demo has signal).
- Dispositions: roughly 40–50% home, 25–30% SNF, 15–20% HHA, one IRF.
- MS-DRG mix: a few 480s, majority 481, a few 482s.
- Sex mix roughly 60/40 F/M (hip fracture epidemiology skews female); ages 68–92.
- At least one of each: outside-claims-only readmission, ED-only visit, open/failed PCP referral, positive CAM, SNF bounce-back.

---

## 5. Cohort size and staging

**Recommended: 15 patients total (patient 1 + 14 new).** Minimum for a credible dashboard is 12; more than 20 adds work without demo value.

- Spread anchor admissions from **late January 2026 through mid-June 2026** (TEAM starts January 2026). With a demo "as of" date in early July 2026, most episodes are completed and 3–4 (admitted in June) are still **active** with days remaining — the roster needs both.
- Maintain a **cohort tracker outside `data/`** (e.g. a private spreadsheet or `docs/` note) recording per patient: patient_id, archetype #, name, MRN, MBI, all FINs, anchor dates, DRG, disposition, readmit date/type. This is where archetype labels live. It also prevents ID collisions.
- **FINs are hospital-wide sequential** (see Section 7): allocate them across the whole cohort in chronological admission order before you start generating, so a January admission has a lower FIN than a June one.

---

## 6. File and folder structure per patient

Copy this structure from patient 1. `{FIN}` = the anchor encounter FIN; `{FIN2}` = readmission/ED-visit FIN if the archetype has one.

```
data/patient/{patient_id}/
├── registration.json                            # demographics, PCP, Medicare coverage
├── problem_list.json                            # active problems, ICD-10 + SNOMED
├── allergies.json
├── social_history.json                          # tobacco, living situation, functional baseline
├── encounter_history.json                       # ALL encounters incl. historical, anchor, readmit
├── care_team_{FIN}.json
├── labs_{FIN}.json                              # LOINC-coded results, pre-op + post-op
├── vitals_{FIN}.json                            # one row per nursing shift/day
├── medications_home_at_admission_{FIN}.json     # admission med rec
├── medications_discharge_{FIN}.json             # discharge med list
├── nursing_assessment_{FIN}.json                # Morse, Braden, CAM, wound checks
├── orders_inpatient_{FIN}.json                  # meds, consults, DME, referrals, activity
├── pt_ot_eval_{FIN}.json
├── referrals_{FIN}.json                         # PCP referral (TEAM requirement)
├── team_beneficiary_notification_{FIN}.txt
├── notes/
│   ├── {FIN}_hp.txt                             # admission H&P
│   ├── {FIN}_rad.txt                            # fracture imaging report
│   ├── {FIN}_anesthesia.txt                     # pre-procedure eval (ASA class lives here)
│   ├── {FIN}_op.txt                             # operative report
│   ├── {FIN}_discharge.txt                      # discharge summary
│   ├── {FIN2}_hp.txt                            # readmission H&P (if readmitted to anchor)
│   └── {FIN2}_rad.txt                           # readmission imaging (if clinically indicated)
├── billing/
│   ├── {FIN}_837I.json                          # anchor inpatient claim, MS-DRG 480-482
│   └── {FIN2}_837I.json                         # readmit inpatient claim (anchor readmits only)
├── interfaces/hl7/
│   ├── MSG{...}.hl7                             # ADT^A01 anchor admit
│   ├── MSG{...}.hl7                             # ADT^A03 anchor discharge
│   ├── ORU{...}.hl7                             # 1-3 lab result messages for anchor stay
│   ├── MSG{...}.hl7                             # ADT^A01 + A03 pair for anchor readmit (if any)
│   └── ORU{...}.hl7                             # readmit labs (optional)
└── feeds/
    └── medicare_claims_{YYYYMMDD}.csv           # lagged CMS claims; filename = file-received date
```

Rules on what varies by archetype:

- **Anchor-stay files are mandatory for everyone** — every file listed for `{FIN}` above, no exceptions.
- **Readmission to anchor hospital** → second FIN gets: encounter_history entry, `{FIN2}_hp.txt`, `{FIN2}_rad.txt` (if imaging fits the story), `vitals_{FIN2}.json`, `billing/{FIN2}_837I.json`, ADT A01+A03 pair, and claim lines in the feeds CSV. It does **not** need care team / PT-OT / TEAM notification files.
- **ED-only visit at anchor** (archetype 6) → encounter_history entry with `patient_class: "Emergency"` and same-day in/out, optionally a short ED note; **no inpatient 837I** — instead a professional claim line (`P...` claim, HCPCS 99284/99285, POS 23) in the feeds CSV. An ADT A04 (ER registration) HL7 message is optional; skip unless you want the extra realism.
- **Outside-hospital readmission** (archetype 4) → **nothing in encounter_history, notes, billing, or HL7** (the anchor hospital can't see it). It exists *only* as institutional claim line(s) in the feeds CSV with a foreign CCN (e.g. `140010`) and a 30–60 day received lag.
- **Historical encounters** (pre-2026): 0–3 per patient in `encounter_history.json` only (no files) — they give the comorbidity story depth (e.g. patient 1's 2024 CHF and 2025 COPD admissions, cross-referenced in the H&P). Use legacy-style FINs (Section 7).
- **Feeds CSV**: one file per patient, named for the *latest* file-received date it contains. Include: anchor inpatient claim line, readmit/ED lines if applicable, and optionally 1–2 mundane Part B professional lines (PCP visit ~99214, outpatient PT) to make the feed look real.

---

## 7. ID conventions

All identifiers are synthetic. **Never** use real MBIs, NPIs, or addresses of real people.

| Identifier | Format | Example | Rules |
|---|---|---|---|
| `patient_id` | small integer | `1`, `2`, `3` | **Catalyst's internal ID** = the folder name. Appears **only** as a JSON field in Catalyst extract files. Hospitals don't know it: it must NEVER appear in notes (.txt), HL7 messages, the TEAM notification, or the feeds CSV — those carry MRN/FIN only. |
| MRN | 5 digits, `10xxx` | `10048` | One per patient, unique across cohort, stable across encounters. Pick `10000 + k` with distinct k values (patient 1 uses 10048 — don't reuse). |
| FIN (encounter #) | **6 digits, zero-padded** | `004821`, `005102` | One per encounter. Hospital-wide sequential-ish: later admission ⇒ higher FIN. Patient 1 holds `004821` and `005102`; allocate the cohort in the `004900`–`007500` range in chronological order, with realistic gaps (increments of ~40–400, never +1). |
| Historical FIN | 6 digits, legacy range | `284711`, `301922` | For pre-2026 encounters in encounter_history only. Use the `28xxxx`–`31xxxx` range so they read as an older numbering era. |
| Medicare MBI | `SYN-MBI-{6 digits}` | `SYN-MBI-000048` | Derived: zero-pad `(MRN − 10000)` to 6 digits. MRN 10237 → `SYN-MBI-000237`. Clearly fake by design. |
| Institutional claim # | `A{CCN}{FIN}{seq}` | `A260001004821001` | `A` + facility CCN (6) + FIN (6) + 3-digit sequence (`001`). |
| Professional claim # | `P{CCN}{FIN}{seq}` | `P260001005102001` | Same pattern with `P`. Outside-facility claims use the foreign CCN. |
| Facility CCN | 6 digits | `260001` | Memorial General — **constant for the whole cohort**. Outside facilities get a different CCN (e.g. Mercy General `140010`). |
| NPI | 10 digits, synthetic | `1234567890` | Reuse Memorial's existing provider pool where the story allows (Section 9); new providers get new made-up 10-digit NPIs. |
| ADT message ID / filename | `MSG{YYYYMMDD}{NNN}` | `MSG20260314001` | Date of the event + 3-digit daily sequence. (Patient 1's admit message uses a timestamp-style ID, `MSG202603101630` — either form is acceptable, but be consistent within a patient.) MSH-10 must equal the filename minus `.hl7`. |
| ORU message ID / filename | `ORU{YYYYMMDDHHMM}` | `ORU202603120800` | Timestamp of result posting. |
| Radiology accession | `RAD-{YYYY}-{FIN}-{NN}` | `RAD-2026-004821-01` | Per exam, per encounter. |
| Order / referral / med IDs | `ORD-{FIN}-{NNN}`, `REF-{FIN}-{NNN}`, `MED-H-{NNN}` / `MED-D-{NNN}` | `ORD-004821-001` | Sequence within the file. |
| MS-DRG | 3-digit string | `"481"` | Anchor stays: `480`/`481`/`482` only. Readmissions use the medically appropriate DRG (e.g. `193` pneumonia, `291` CHF, `377` GI bleed). |

**Shared constants across the cohort** (copy from patient 1, do not vary):

- Facility: `MEMORIAL GENERAL HOSPITAL` (notes/TEAM letter), `MEMORIAL` (HL7 sending facility), CCN `260001`.
- HL7: sending app `EPIC` (labs: `LIS`), version `2.5`, message structure per patient 1's segments.
- JSON `source` values: `EPIC_*` / `EHR_*` exactly as patient 1 uses them per file type.
- Locale: Springfield, IL addresses; `555-01xx` phone numbers; timezone offset `-06:00` on all JSON timestamps (match patient 1's convention; don't mix offsets within a patient).
- Payer: `MEDICARE`, plan `Medicare Part A/B`.

---

## 8. Timeline rules

Build each patient's timeline in this order, then derive every timestamp from it. All events for a patient must be strictly chronological across every file.

| Event | Rule |
|---|---|
| Fall / injury | Day 0, usually at home; mechanism appropriate to age (ground-level mechanical fall dominates) |
| ED arrival | Same day as fall, hours after (EMS or family transport) |
| Fracture X-ray | Within ~1–2h of ED arrival; radiology report signed within ~1h of exam |
| Inpatient admit (ADT A01) | Same day as ED arrival, after imaging + ortho consult (patient 1: fall AM → admit 16:30) |
| Pre-op labs | Between ED arrival and surgery — **never before the fall** |
| Surgery | 24–48h after admission for most; >48–72h only for the delayed-surgery archetype (anticoagulation reversal) — document the reason |
| Anesthesia pre-op eval | Morning of surgery, signed before OR time |
| Op note | Signed within hours of the case, same day |
| Post-op labs (POD1) | Morning after surgery (Hgb drop of ~0.5–1.5 vs pre-op is realistic) |
| PT/OT eval | POD 1–2 |
| Vitals | One row at admission + one per day ~07:00, trending toward normal (or not, per story); pain score decreasing post-op |
| PCP referral + DME orders | 1–2 days before discharge |
| TEAM beneficiary notification | On or up to 1 day before discharge date |
| Discharge (ADT A03) | LOS 3–7 days (longer for DRG-480/SNF stories); discharge summary signed morning of discharge, before the discharge time |
| **Episode window** | Discharge date + 30 days — pin this down first, then place post-discharge events inside it |
| PCP appointment | Scheduled within 7 days of discharge (TEAM expectation); completed / no-showed / never-scheduled per archetype |
| Ortho follow-up | ~2 weeks post-discharge |
| ED-only visit | Day 5–20 post-discharge |
| Readmission | Day 5–25 post-discharge (archetype-specified); readmit LOS 2–5 days |
| 837I `submitted_date` | 2–5 calendar days after that encounter's discharge |
| CMS claims feed `FILE_RECEIVED_DT` | **30–60 days after** the claim's service dates (patient 1: March discharge → April/May receipt). Outside-hospital claims sit at the long end (~45–60 days). The feed filename matches the latest received date in the file. |

Sanity anchors from patient 1: fall + admit 03/10, surgery 03/11, discharge 03/14 (LOS 4), readmit 03/26 (day 12), anchor claim submitted 03/16, received by CMS feed 04/15, readmit claims received 05/10.

---

## 9. Cross-file consistency rules

These are the lessons from reviewing patient 1. An inconsistency here is the most likely failure mode — one fact is asserted in up to eight places.

1. **Identity block everywhere:** name, MRN, DOB, sex must match exactly across registration, every JSON header, every note header, every HL7 PID segment, the 837I files, and the TEAM letter. HL7 PID format: `10048^^^MEMORIAL^MR` and `CHEN^ROBERT^M`, DOB as `YYYYMMDD`.
2. **`patient_id` placement:** present in every JSON extract as the join key; absent from every .txt, .hl7, and .csv file (hospitals send MRN/FIN, not Catalyst IDs).
3. **FIN threads the encounter:** the anchor FIN must be identical in encounter_history, every per-encounter JSON filename *and* its `fin` field, note headers, HL7 PV1-19, the 837I `fin`/claim number, and the feeds CSV `FIN` column.
4. **Timestamps agree to the minute** where the same event appears twice: admit/discharge datetimes in encounter_history = ADT A01/A03 MSH-7, EVN, and PV1-44/45 = note headers = 837I dates (`YYYYMMDD`, plus `discharge_hour`) = CSV `CLM_FROM_DT`/`CLM_THRU_DT`.
5. **Every timestamp postdates its cause.** Labs after ED arrival, op note after surgery, discharge summary before discharge time. *Known flaw in patient 1: the ED CMP (`labs_004821.json`, `ORU202603091420.hl7`) is dated 03/09 — the day before the documented fall. Do not replicate this class of error; patient 1's shape is the template, not every one of its timestamps.*
6. **Diagnoses reconcile across four places:** problem list (chronic conditions) ⊇ H&P PMH = discharge summary diagnosis list ≈ 837I `other_diagnoses` (chronic conditions are `poa: "Y"`; complications arising in-house are `poa: "N"`) ≈ HL7 DG1 segments (top 3–4). The principal diagnosis (`S72.*A`) appears in encounter_history, 837I, DG1-1, and both H&P and discharge summary.
7. **The DRG must be earned.** 481 needs ≥1 plausible CC in `other_diagnoses`; 480 needs ≥1 MCC; 482 has neither. Don't give a 482 patient a seven-problem list.
8. **Medications tell one story:** home med list = H&P "HOME MEDICATIONS" = discharge summary "HOME MEDICATIONS ON ADMISSION"; discharge med list = discharge summary "DISCHARGE MEDICATIONS" = relevant inpatient orders; anticoagulant held/resumed logic appears in med rec notes, H&P plan, anesthesia note, and discharge summary consistently. Every chronic problem should have a matching med (or a documented reason it doesn't).
9. **Allergies match** across allergies.json, H&P, anesthesia note, discharge summary — and constrain antibiotic choices in the story (patient 1: PCN/sulfa allergy → levofloxacin for pneumonia).
10. **Disposition is asserted in six places:** encounter_history (`discharge_disposition_code` + display), 837I `discharge_status`, ADT A03 PV1-36, discharge summary "DISCHARGE DISPOSITION", PT/OT recommendation, and (for SNF/IRF/HHA) a named receiving facility in the discharge note. Codes: `01` home, `03` SNF, `06` HHA, `62` IRF, `50`/`51` hospice.
11. **Providers are one cast:** the attending in encounter_history = HL7 PV1-7 = note signatures = 837I `attending_npi` = care_team "Attending". The PCP in registration = care team = referral target = discharge summary follow-up. Reuse Memorial's pool (Mitchell/ortho, Okonkwo/hospitalist, Patel/anesthesia, Hartman/radiology, Torres PA-C, Walsh PT, Kim OT, Nguyen RN CM) freely; each patient gets their own PCP (new name + NPI). Add a second ortho surgeon and hospitalist so one doctor isn't doing 15 cases.
12. **Claims math:** CSV `CLM_ID` = 837I `claim_number`; `CLM_PMT/LINE_PMT_AMT` ≈ 60–75% of 837I `total_charges`; `DRG_CD` matches; institutional lines have CCN + blank NPI, professional lines have NPI + blank CCN (patient 1's CSV shows both patterns).
13. **Emergency contact = caregiver** in the story: registration's emergency contact reappears in social history living situation, H&P social history, and the TEAM letter acknowledgment. "Lives alone" patients have a non-cohabiting contact (neighbor, out-of-town child) — consistently.
14. **Narrative cross-references are gold:** patient 1's H&P cites prior FINs; its readmission H&P cites the hip surgery and FIN 004821. Do this — it's cheap and makes the data feel real. But every cross-reference must resolve to something that actually exists in the files.
15. **Lab values thread into notes:** values quoted in the H&P ("albumin 3.2") and anesthesia note must equal `labs_{FIN}.json` and the ORU messages exactly, including units and flags.

---

## 10. Coding quick reference

Plausibility matters more than perfect grouper fidelity, but stay inside these menus.

**Principal diagnosis (pick per archetype; 7th char `A`):**

| Fracture | Right | Left |
|---|---|---|
| Intertrochanteric, displaced | `S72.141A` | `S72.142A` |
| Femoral neck (midcervical), displaced | `S72.031A` | `S72.032A` |
| Subtrochanteric, displaced | `S72.211A` | `S72.212A` |
| Femoral shaft, unspecified | `S72.301A` | `S72.302A` |

**Procedures:**

| Procedure | ICD-10-PCS (R / L) | CPT | Typical for |
|---|---|---|---|
| Hip hemiarthroplasty | `0SRB02A` / `0SR902A` | `27125` | Femoral neck, some intertroch (patient 1's pattern) |
| IM nail (cephalomedullary) | `0QS606Z` / `0QS706Z` | `27245` | Intertroch, subtroch |
| ORIF femoral neck | `0QS604Z` / `0QS704Z` | `27236` | Femoral neck |
| IM nail, femoral shaft | `0QS806Z` / `0QS906Z` | `27506` | Shaft |

**Severity levers:** MCC examples — acute kidney injury `N17.9`, acute respiratory failure `J96.01`, sepsis `A41.9`, acute systolic CHF `I50.21`. CC examples — CKD 3 `N18.31`/`N18.30`, afib `I48.91`, COPD w/ exacerbation `J44.1`, malnutrition `E44.0`. Neutral (no CC): HTN `I10`, uncomplicated T2DM `E11.9`, osteoporosis `M81.0`, hyperlipidemia `E78.5`.

**Readmission DRGs (anchor readmits):** pneumonia `193`, CHF `291`, GI bleed `377`, UTI `690`, aspiration pneumonia `177`.

**Labs (LOINC, from patient 1):** albumin `1751-7`, creatinine `2160-0`, hemoglobin `718-7`, WBC `6690-2`, platelets `777-3`, sodium `2951-2`, potassium `2823-3`. Add INR `34714-6` for warfarin patients.

---

## 11. Per-archetype generation checklist

For each patient, before writing any file, decide and record in the cohort tracker:

- [ ] Archetype # and one-sentence story arc
- [ ] Demographics: name (no reuse across cohort), age/DOB, sex, address (Springfield IL area), emergency contact + relationship
- [ ] Living situation + functional baseline (must support the risk level)
- [ ] Problem list (0–8 problems scaled to archetype) and matching home med list
- [ ] Fracture type + laterality, procedure, MS-DRG + the CC/MCC that justifies it
- [ ] ASA class (II for archetype 1/9, III for most, IV sparingly)
- [ ] All IDs: MRN, MBI (derived), anchor FIN (+ readmit FIN), claim numbers
- [ ] Full timeline (Section 8) from fall through episode day 30, including claims lag dates
- [ ] Disposition + receiving facility name (if SNF/IRF/HHA — invent local names: "Oakwood Rehabilitation", "Prairie View Skilled Nursing", etc.)
- [ ] PCP name/NPI + referral outcome (completed / scheduled / no-show / never placed)
- [ ] Post-discharge events: readmit (where, when, why) / ED visit / none
- [ ] Lab value trajectory consistent with risk (low albumin + anemia for high risk; normal for low risk)
- [ ] Nursing assessment scores consistent with risk (Morse ≥45 high, ≤25 low; CAM per story)

---

## 12. Step-by-step workflow for patient N

1. **Pick the archetype** from Section 4 (next unfilled row) and complete the Section 11 checklist in the cohort tracker. Reserve FINs consistent with cohort-wide chronology.
2. **Create the folder skeleton:** `data/patient/{N}/` with `notes/`, `billing/`, `interfaces/hl7/`, `feeds/`.
3. **Write `registration.json`** — copy patient 1's schema; new demographics, PCP, MBI.
4. **Write the chart-level files:** `problem_list.json`, `allergies.json`, `social_history.json`. These lock in the clinical facts everything else must honor.
5. **Write `encounter_history.json`:** 0–3 historical encounters (legacy FINs, no files) + anchor encounter + readmit/ED encounter if the archetype has one. This file is the timeline's spine.
6. **Write the anchor-stay clinical JSONs** in story order: `medications_home_at_admission_{FIN}` → `labs_{FIN}` → `vitals_{FIN}` → `nursing_assessment_{FIN}` → `orders_inpatient_{FIN}` → `pt_ot_eval_{FIN}` → `care_team_{FIN}` → `referrals_{FIN}` → `medications_discharge_{FIN}`.
7. **Write the notes** in chronological order: `_rad` → `_hp` → `_anesthesia` → `_op` → `_discharge`. Pull every quoted vital, lab, med, and date from the JSONs you just wrote — never from memory. Match patient 1's headers, section names, and signature blocks.
8. **Write the HL7 messages:** ADT A01, ORU message(s) mirroring `labs_{FIN}.json`, ADT A03. Copy patient 1's segment structure field-for-field, substituting PID/PV1/DG1/OBX content.
9. **Write `billing/{FIN}_837I.json`:** diagnoses from the discharge summary list, procedure code + date from the op note, charges scaled to LOS/DRG (patient 1: ~$41k for a 4-day 481; range $35k–$60k).
10. **Generate the readmission/ED artifacts** if applicable (repeat steps 6–9 in reduced form per Section 6). For the outside-readmission archetype, skip entirely — it exists only in step 11.
11. **Write `feeds/medicare_claims_{YYYYMMDD}.csv`:** patient 1's exact header row; one line per claim with correct lag dates; filename = latest `FILE_RECEIVED_DT`.
12. **Write `team_beneficiary_notification_{FIN}.txt`** from patient 1's letter, substituting patient, dates, caregiver, and case manager.
13. **Run the quality checklist (Section 13).** Fix everything before moving to patient N+1.
14. **Update the cohort tracker** with final IDs and dates.

---

## 13. What NOT to include

- **No persona/archetype labels in any data file.** No `"archetype"`, `"risk_level": "high"`, `"persona"`, or storytelling comments. Archetype bookkeeping lives only in the tracker.
- **No app events** (check-ins, med adherence, symptom reports, engagement). Deferred.
- **No derived/computed fields:** no risk scores, episode-day counters, readmission flags, Charlson/HCC scores, alert priorities. Catalyst computes these.
- **No `patient_id` in hospital-native artifacts** (.txt notes, .hl7, .csv, TEAM letter).
- **No data the anchor hospital couldn't have:** no clinical notes from outside hospitals or SNFs, no real-time outside ADT/HIE feeds, no CMS target-price or eDFR summary files, no SNF EHR extracts. Outside utilization surfaces only via the lagged claims CSV.
- **No non-FFS payers** on SHFFT patients (Medicaid may appear as *secondary* for the dual-eligible archetype only).
- **No real-world identifiers:** no real MBI format (use `SYN-MBI-*`), no real people's names/NPIs/addresses, no real facility names beyond our invented ones.
- **No FHIR bundles, C-CDA, or X12 EDI raw syntax** — the 837I files stay as flat "837I-shaped" JSON like patient 1's.
- **No perfect data.** Real charts have benign gaps (a missing wound check, a `null` NPI for the case manager, sparse historical records). Include benign imperfection; never include *contradictions*.
- **No README or metadata files inside `data/patient/{N}/`.**

---

## 14. Quality checklist before marking a patient complete

Run through every item. A patient with any unchecked item is not done.

### Automated checks (from repo root)

```bash
# All JSON parses
find data/patient/N -name "*.json" -exec jq empty {} \;

# The anchor FIN appears consistently — review every hit
grep -rn "004821" data/patient/N/ | less   # substitute the real FIN

# patient_id leaked into hospital-native files? (must return nothing)
grep -rn "patient_id" data/patient/N/notes/ data/patient/N/interfaces/ data/patient/N/feeds/

# MRN/DOB consistency — every hit should show identical values
grep -rn "10048\|19431108\|1943-11-08" data/patient/N/   # substitute real MRN/DOB
```

### Identity & IDs

- [ ] Name, MRN, DOB, sex identical in every file (JSON, notes, HL7 PID, 837I, TEAM letter)
- [ ] MBI = `SYN-MBI-` + zero-padded (MRN − 10000); same in registration, 837I, CSV `BENE_ID`, TEAM letter
- [ ] FINs unique cohort-wide and chronologically ordered vs other patients (check tracker)
- [ ] Claim numbers follow `A/P + CCN + FIN + seq`; CSV `CLM_ID` = 837I `claim_number`
- [ ] HL7 filenames = MSH-10 message control IDs
- [ ] No ID collisions with any existing patient (MRN, FIN, claim #, provider NPIs for *new* providers)

### Timeline

- [ ] Every timestamp in every file is on or after the fall and strictly ordered (labs > ED arrival; op note > surgery; discharge summary signature < discharge time)
- [ ] Admit/discharge datetimes identical across encounter_history, ADT, notes, 837I, CSV
- [ ] Surgery within 24–48h of admit (or documented delay); LOS 3–7 days
- [ ] Post-discharge events inside the 30-day window on the intended day
- [ ] 837I submitted 2–5 days post-discharge; CSV `FILE_RECEIVED_DT` 30–60 days post-service; feed filename matches latest received date

### Clinical coherence

- [ ] MS-DRG ∈ {480, 481, 482} on the anchor claim and justified by the secondary diagnosis list
- [ ] Problem list ⇄ meds ⇄ note PMH ⇄ claim diagnoses all reconcile; allergies consistent and honored in med choices
- [ ] Lab values quoted in notes equal the JSON/ORU values; lab trajectory matches the risk story
- [ ] Disposition identical in all six locations (Section 9, rule 10); PT/OT recommendation supports it
- [ ] ASA class, Morse/Braden/CAM scores consistent with the archetype's risk level
- [ ] Attending, PCP, and care team consistent everywhere; readmission attended by a medicine provider, not the surgeon

### TEAM artifacts

- [ ] Beneficiary notification present, dated ≤ discharge, acknowledgment completed
- [ ] PCP referral present in both referrals and orders files with the archetype's intended status
- [ ] Payer is Medicare FFS

### Archetype fidelity

- [ ] The patient actually tells its archetype's story — a reviewer reading only the data files (no tracker) should be able to reconstruct the intended clinical arc
- [ ] The archetype's "key data to emphasize" (Section 4) is present and prominent
- [ ] No persona labels, app events, or derived scores anywhere in the folder

---

*When all 15 patients are complete, do one cohort-level pass: no duplicate names/MRNs/FINs, admission dates spread Jan–Jun 2026, disposition/readmit/DRG mix matches Section 4's balance targets, and 3–4 episodes are still active as of the demo date.*
