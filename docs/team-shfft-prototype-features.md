# TEAM / SHFFT Post-Discharge Monitoring Prototype

Product concept for hospital and patient-facing tools supporting **Surgical Hip and Femur Fracture Treatment (SHFFT)** episodes under CMS's **Transforming Episode Accountability Model (TEAM)**.

**Goal:** Monitor patients after discharge to catch adverse events early, reduce avoidable utilization, and support TEAM episode management.

**Scope:** SHFFT only (prototype wedge).

**References:**
- [TEAM model overview (CMS)](https://www.cms.gov/priorities/innovation/innovation-models/team-model)
- [TEAM fact sheet (PDF)](https://www.cms.gov/files/document/team-model-fs.pdf)
- [TEAM overview webcast slides (PDF)](https://www.cms.gov/priorities/innovation/files/team-ovw-webinar-slides.pdf)

---

## Framing: TEAM + SHFFT-only prototype

**TEAM** (Transforming Episode Accountability Model) is a mandatory CMS episode-based payment model starting January 2026. Hospitals are accountable for **Medicare FFS** spending and quality from anchor admission through **30 days post-discharge**.

**SHFFT** (Surgical Hip and Femur Fracture Treatment) is one of five episode types, **inpatient only**, MS-DRG **480–482**. It is a strong first wedge because:

- Elderly, medically complex population (~8–15% 30-day readmission)
- Readmissions are mostly **medical** (pneumonia, cardiac, infection) not surgical
- Surgical risks still matter: wound issues, DVT, dislocation (arthroplasty)
- Discharge is often to **SNF/IRF/home health**, not straight home — coordination is the hard part
- TEAM requires **PCP referral at discharge** and allows **telehealth + patient engagement incentives** (including technology)

This product maps cleanly to: **catch deterioration early → reduce avoidable utilization → support TEAM episode management**.

---

## Hospital dashboard — core features

### 1. Episode roster & timeline (TEAM ops view)

- Active SHFFT episodes with **days remaining** in the 30-day window
- Anchor admission date, procedure type (ORIF vs hemi/THA), MS-DRG, surgeon, discharge date/disposition (home, SNF, IRF, HHA)
- Episode status: active / completed / canceled (death during stay, etc.)
- Filter/sort by risk tier, engagement level, disposition, care setting

### 2. Pre-op & index stay summary (clinical context)

- **Comorbidity snapshot**: ASA, Charlson/elixhauser-style summary, key flags (CHF, COPD, CKD, diabetes, anticoagulation, cognitive impairment)
- **Pre-op labs/vitals** where available: albumin, creatinine, hemoglobin (known SHFFT readmission predictors)
- **Index events**: time to surgery, LOS, intra/post-op complications (DVT, delirium, transfusion, ICU)
- **Procedure details**: fixation vs arthroplasty, weight-bearing status, DME ordered (walker, etc.)

### 3. SHFFT-specific risk score

A composite **30-day adverse event risk** score, not a generic surgical score. Prototype inputs:

| Category | Examples |
| --- | --- |
| Patient | Age ≥80, ASA 3–4, comorbidity burden, cognitive impairment, living alone |
| Clinical | Low albumin, anemia, post-op DVT, delirium |
| Process | Delay to surgery, prolonged LOS, weekend discharge |
| Disposition | SNF vs home without adequate support |

**Output:** Low / Medium / High with top 3 modifiable drivers and suggested interventions (e.g. "respiratory symptom monitoring," "fall prevention pathway").

### 4. Live patient signal feed

A unified timeline per patient from the app (and eventually devices):

- Daily check-in completion / missed check-ins
- Symptom reports (pain, fever, SOB, confusion, wound concern, fall)
- Medication adherence self-report + quiz scores
- Mobility / PT exercise completion
- Escalations triggered (patient tapped "I need help" or failed a safety screen)

### 5. Triage & work queue

- **Priority inbox** sorted by risk + signal severity
- Suggested actions: call patient/caregiver, notify PCP, recommend telehealth, flag for case manager, recommend ED vs urgent eval
- Assignment to roles (ortho navigator, case management, SNF liaison)
- Audit trail of outreach and resolution

### 6. Care transition & TEAM compliance tracker

- **PCP referral status** (required by TEAM) — referred, appointment scheduled, completed
- Discharge instruction acknowledgment (from app)
- Post-acute partner status if SNF/IRF/HHA (even if manual entry in v1)
- TEAM **beneficiary notification** acknowledgment (CMS template compliance)

### 7. Episode economics (prototype-light)

- Estimated **episode spend to date** vs target (even if mocked or claims-delayed in v1)
- Cost drivers flagged: readmission, ED visit, extended SNF (when claims feed exists)
- Link adverse signals to **predicted financial exposure**

### 8. Population analytics (SHFFT-only)

- Engagement rate, check-in completion, time-to-first-touch post-discharge
- Signal → outcome correlation (for pitch deck / pilot learning)
- Stratified views by disposition, age band, social risk (dual-eligible, ADI proxy) — TEAM adjusts for these

---

## Patient app — core features

SHFFT patients skew **older, cognitively vulnerable, and often not on smartphones**. Design for **large text, simple flows, caregiver proxy mode, and optional SMS/phone fallback**.

### 1. Onboarding & care team connection

- Discharge-day setup (ideally before leaving hospital): confirm identity, add caregiver, language preference
- Plain-language summary of surgery, weight-bearing rules, and who to call
- Download/access via link, QR at bedside, or caregiver setup

### 2. Daily recovery check-in (2–3 min)

- Mood, pain level, mobility today
- **Red-flag screen**: fever, worsening wound, new leg swelling, chest pain, SOB, confusion, fall since yesterday
- Branching logic: green → encouragement; yellow → education + notify care team; red → urgent guidance + immediate dashboard alert

### 3. Medication navigator

- Personalized med list from discharge (anticoagulant, analgesic, osteoporosis therapy, etc.)
- Reminders with confirm/skip/snooze
- **Short quizzes** ("Why are you taking this blood thinner?") to reinforce understanding
- Missed-dose pattern surfacing to dashboard

### 4. Post-op instruction coach (SHFFT-specific)

- Weight-bearing and mobility rules (procedure-specific)
- Fall prevention tips (critical for this population)
- Wound care basics + photo upload option (with clear "when to call" guidance)
- DVT signs education
- Pneumonia prevention / breathing exercises (high-yield for medical readmissions)

### 5. Rehab & mobility tracker

- PT/OT home exercise checklist (prescribed movements, not generic)
- Optional step/mobility self-report ("Did you walk with your walker today?")
- Progress nudges tied to recovery milestones

### 6. Appointment & follow-up hub

- Ortho follow-up, PCP visit (TEAM-relevant), lab appointments
- Reminders + "Did you attend?" capture
- One-tap request to reschedule or ask a question

### 7. "Get help" & escalation

- Non-emergency message to care team
- Clear ED vs call-911 decision support
- After-hours routing rules

### 8. Caregiver mode

- Separate login or linked profile
- Caregiver completes check-ins on behalf of patient
- Notifications to caregiver when patient misses check-ins or triggers alerts

---

## Suggested prototype scope (MVP vs later)

| MVP (demo/pilot credible) | Phase 2 |
| --- | --- |
| Manual/registry patient enrollment | EHR/ADT auto-enrollment |
| Risk score from structured intake form | Risk score from EHR + claims |
| Daily check-in + med reminders + quizzes | RPM devices (pulse ox, BP) |
| Dashboard triage queue | Claims-based spend tracking |
| Caregiver mode | SNF/partner portal |
| PCP referral checklist | Direct PCP scheduling integration |

---

## Build challenges

### 1. EHR & data integration

Hospitals will not manually enter everything. Eventually you need ADT feeds, discharge summaries, problem lists, and med reconciliation from Epic/Cerner/etc. FHIR helps but site-by-site integration is slow and expensive.

### 2. Defining a credible risk score

Off-the-shelf scores (ASA, Charlson) are not enough. You will need SHFFT-specific validation or a clinical informatics partner. Over-alarming erodes trust; under-alarming misses the value prop.

### 3. Alert fatigue & workflow fit

The dashboard must route to **existing roles** (case management, ortho APP, SNF coordinator). If it is "another inbox," adoption dies. Need SLAs, ownership rules, and EHR note export.

### 4. Multimodal patient access

Many SHFFT patients will not use an app. You need caregiver flows, SMS IVR, tablet at SNF, or hospital-funded devices. Engineering is easy; **distribution and training** are hard.

### 5. Clinical content maintenance

Procedure-specific pathways (ORIF vs hemiarthroplasty), anticoagulation regimens, and institution-specific discharge instructions require clinician-authored, versioned content — not one static quiz library.

### 6. HIPAA, consent, and liability

Patient-generated data, wound photos, and triage recommendations sit in a regulated zone. You need clear scope (education + routing, not diagnosis), BAAs, audit logs, and clinical oversight policies.

### 7. Real-time vs batch

TEAM reconciliation uses **claims** (lagged). Your monitoring is real-time. Bridging "patient says SOB today" to "ED visit in 3 days" and episode spend requires data pipelines with very different latency.

---

## Feasibility & practicality challenges

### 1. Patient population fit

SHFFT is one of the **hardest** populations for digital engagement: age, cognition, vision, dexterity. Feasibility improves sharply if you design for **caregivers and post-acute staff**, not just patients.

### 2. Discharge disposition reality

A large share will not go home. If the patient is in SNF, the "navigator" may need to be the **SNF nurse** or a hospital-to-SNF handoff workflow — otherwise you monitor the wrong person in the wrong setting.

### 3. TEAM quality measures are not episode-PRO for SHFFT

PY1 TEAM quality includes hospital-wide readmission, PSI 90, and THA/TKA PRO (LEJR-focused). Your product will not directly move CMS quality scores for SHFFT in year 1 — the pitch is **episode spend + readmission avoidance**, not PRO reporting.

### 4. Medicare FFS only (for TEAM attribution)

TEAM episodes are **Traditional Medicare** only. Commercial, MA, and Medicaid patients may benefit clinically but will not count for TEAM reconciliation unless you expand scope.

### 5. Who pays?

Hospitals under downside risk have incentive; SNFs and PCPs may not engage without payment or workflow benefit. You need a **buyer** (hospital episode management / ortho service line) and a **usage wedge** (case managers love triage queues).

### 6. Evidence expectations

Hospitals will ask: "Does this reduce readmissions?" Digital post-discharge programs show mixed results; **high-touch + risk-stratified** models work better. Plan for a pilot with clear endpoints (30-day readmission, ED visits, engagement by risk tier).

### 7. Competing hospital initiatives

TEAM overlaps with ACOs, care management vendors, home health, and existing RPM programs. Position as **SHFFT episode command center** that complements, not replaces, those channels.

### 8. Regulatory alignment (opportunity)

TEAM explicitly allows **telehealth from home** and **in-kind technology incentives** for adherence and readmission reduction — useful for hospital procurement and compliance framing.

---

## SHFFT-specific design principles

1. **Medical complications first** — screen for respiratory infection, cardiac symptoms, delirium, not just wound checks.
2. **Falls are first-class** — new fall = high-priority signal.
3. **Caregiver is a primary user** — not an edge case.
4. **Disposition-aware** — home vs SNF vs HHA changes who gets which tasks.
5. **PCP handoff is a product feature** — TEAM requires it; track it visibly on the dashboard.

---

## Possible next steps

- Prioritized MVP backlog (user stories + wireframe-level screen list)
- One-page pitch framing the product for TEAM Track 2/3 hospitals starting SHFFT episodes in 2026
- Clinical pathway content outline (ORIF vs arthroplasty branches)
