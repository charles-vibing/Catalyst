# Core functionality — dashboard & patient app

What Catalyst needs to do for **TEAM SHFFT** post-discharge monitoring. This is the build checklist distilled from the product concept, the synthetic cohort, and the hospital dashboard mockup.

**Users**

| Surface | Primary users |
|---|---|
| **Hospital dashboard** | Ortho navigator, case management, SNF liaison, episode ops |
| **Patient app** | Patient and/or **caregiver** (often the real daily user) |

**Episode framing:** Memorial General is accountable from anchor admission through **30 days after discharge** for Medicare FFS SHFFT episodes (MS-DRG 480–482).

---

## A. Hospital dashboard

### Must-have (MVP)

| # | Capability | Why it matters |
|---|---|---|
| D1 | **Episode roster** | See all active SHFFT episodes: patient, admit/discharge, procedure, MS-DRG, disposition (home / HHA / SNF / IRF), days left in the 30-day window, status (active / completed) |
| D2 | **Risk tier on every row** | Low / Medium / High so staff can sort and prioritize without reading the full chart |
| D3 | **Filter & sort** | By risk, disposition, open signal, PCP gap, days remaining |
| D4 | **Patient episode view** | Index-stay summary: comorbidities, key labs (albumin, Hgb, creatinine), procedure, LOS, weight-bearing / DME notes |
| D5 | **Risk drivers + suggested actions** | Top reasons for the score and concrete next steps (e.g. respiratory watch, fall pathway, reschedule PCP) |
| D6 | **Live signal timeline** | Check-ins completed/missed, symptom flags (pain, fever, SOB, confusion, wound, fall), med adherence, “I need help” |
| D7 | **Triage / work queue** | Priority inbox sorted by risk × signal severity; assign to a role; mark resolved with a short note |
| D8 | **PCP referral tracker** | TEAM-required: not referred / scheduled / completed / no-show / declined — visible as a gap on the roster |
| D9 | **Disposition-aware context** | Home vs HHA vs SNF vs IRF changes who to contact and what “normal” engagement looks like |
| D10 | **Readmission / bounce visibility** | Flag anchor readmits, ED-only returns, **HIE ADT alerts** for outside admits (when present), and **outside-hospital claims** when the lagged Medicare feed arrives |

### Should-have (soon after MVP)

| # | Capability | Why it matters |
|---|---|---|
| D11 | **TEAM / transition compliance strip** | Beneficiary notification ack, discharge-instruction ack, post-acute partner named |
| D12 | **Outreach audit trail** | Who called/messaged whom, when, and outcome |
| D13 | **Population KPIs** | Active count, needs-attention count, check-in rate, PCP gap count, 30-day readmit count |
| D14 | **Care setting handoff status** | Manual or lightweight SNF/IRF/HHA status when the facility owns day-to-day care |

### Later

| # | Capability |
|---|---|
| D15 | Episode spend vs target (claims-lag aware) |
| D16 | EHR / ADT auto-enrollment into the roster |
| D17 | SNF / partner portal |
| D18 | Deep analytics (signal → outcome, social-risk strata) |

---

## B. Patient app (and caregiver mode)

Design constraints: large text, short flows, **caregiver proxy as first-class**, SMS/phone fallback acceptable for MVP.

### Must-have (MVP)

| # | Capability | Why it matters |
|---|---|---|
| A1 | **Onboarding** | Confirm identity, add caregiver, language preference; plain-language “what surgery / who to call” |
| A2 | **Daily recovery check-in (2–3 min)** | Mood, pain, mobility + red-flag screen (fever, wound, swelling, chest pain, SOB, confusion, fall) |
| A3 | **Severity routing** | Green → encourage; yellow → educate + notify care team; red → urgent guidance + **dashboard alert** |
| A4 | **Medication list + reminders** | Discharge meds with confirm / skip / snooze; missed doses visible on dashboard |
| A5 | **Get help** | Message care team + clear “call 911 vs ED vs wait for callback” guidance |
| A6 | **Caregiver mode** | Caregiver can complete check-ins and receive miss/alert notifications |
| A7 | **PCP / follow-up awareness** | Show upcoming PCP (and ortho) visit; capture “Did you attend?” |

### Should-have (soon after MVP)

| # | Capability | Why it matters |
|---|---|---|
| A8 | **SHFFT instruction coach** | Weight-bearing rules, fall prevention, wound basics, DVT signs, breathing / pneumonia prevention |
| A9 | **Med understanding quizzes** | Short “why this blood thinner?” prompts; weak scores surface to dashboard |
| A10 | **PT / mobility checklist** | Prescribed home exercises + “walked with walker today?” |
| A11 | **Appointment hub** | Reminders + one-tap “need to reschedule / ask a question” |

### Later

| # | Capability |
|---|---|
| A12 | Wound photo upload with clinical routing rules |
| A13 | RPM devices (pulse ox, BP) |
| A14 | Multimodal access (SMS/IVR, SNF tablet workflow) |

---

## C. How the two sides connect

These are the **shared contracts** both products must support:

```
Patient / caregiver app                     Hospital dashboard
─────────────────────                     ──────────────────
Daily check-in / red flags      ──►       Signal timeline + triage queue
Missed check-ins                ──►       Engagement flag on roster
Med confirm / miss              ──►       Adherence pattern on chart
"Get help"                      ──►       Urgent queue item
PCP attend / no-show            ──►       PCP referral status
Caregiver linked                ──►       Who to call on outreach
```

Hospital-side data the app does **not** invent (comes from EHR / claims / registry):

- Episode window dates, FIN/MRN, DRG, disposition  
- Discharge med list, problem list, key labs  
- Outside readmits (claims feed)  
- TEAM referral / notification status (until the app captures ack)

---

## D. Prototype build order (suggested)

1. **Roster + patient episode view** from synthetic / SQLite cohort (D1, D4, D9)  
2. **Risk tier + drivers** (rule-based MVP is fine) (D2, D5)  
3. **Mock signals + triage queue** (D6, D7) — matches current HTML mockup  
4. **PCP status on roster** (D8)  
5. **App: check-in + caregiver + get help** (A1–A3, A5–A6) wired into the queue  
6. **Med reminders** (A4)  
7. Compliance strip + KPIs (D11, D13)  
8. Instruction coach / quizzes / PT (A8–A10)

---

## E. Explicitly out of scope for early prototype

- Diagnosing or prescribing in the app (education + routing only)  
- Replacing the EHR chart  
- Full claims reconciliation / payment calculation  
- Non-SHFFT episode types  
- Medicare Advantage / commercial attribution for TEAM

---

## F. Mockups

| Mockup | Covers |
|---|---|
| [mockups/hospital-dashboard.html](./mockups/hospital-dashboard.html) | **D1–D10** hospital MVP (roster, risk, filters, episode view, drivers, timeline, triage, PCP, disposition, readmit/HIE/claims). No D11–D14 KPI/compliance strip. |

Patient-app screens are not mocked yet.
