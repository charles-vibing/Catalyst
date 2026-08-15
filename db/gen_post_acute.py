#!/usr/bin/env python3
"""Generate the post-acute cost layer the executive view runs on (D13 / D15).

The base cohort under data/patient/ ships hospital-side money only: the anchor
inpatient claim, outside readmits, and a handful of professional lines. It has
no SNF / HHA / IRF / DME / outpatient-therapy claims and no facility identity
for post-acute placement, so there is nothing to group an exec view by. This
script fills that gap **additively** — it writes three new files under
data/feeds/ and never touches the 50 patient folders:

    data/feeds/provider_facility.csv     provider dimension (CCN → name, setting)
    data/feeds/post_acute_claims.csv     claim lines, same column shape as the
                                         per-patient medicare_claims_*.csv feeds
    data/feeds/episode_target_price.csv  TEAM target price per anchor episode

db/load_cohort.py reads all three. Claim lines land in the existing
medicare_claim_line table — no schema change was needed for them, because that
table already carries prvdr_ccn / clm_type / hcpcs_cd / line_pmt_amt / service
dates.

Input is source JSON only (registration, encounter_history, problem_list,
referrals), never a built catalyst.db, so this can run before or after a cohort
load without ordering surprises.

Output is deterministic: every random draw comes from a Random seeded on the
patient_id, so re-running produces byte-identical files and demo numbers never
move between runs.

    python3 db/gen_post_acute.py            # → data/feeds/*.csv

Dates note: lines are generated for the **whole** 30-day episode regardless of
the as-of clock. The exec API filters by service date at query time, so an
in-flight episode reports spend-to-date and moving CATALYST_AS_OF just works.
See backend/app/routers/exec_view.py.
"""

from __future__ import annotations

import csv
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = REPO_ROOT / "data" / "patient"
FEEDS_DIR = REPO_ROOT / "data" / "feeds"

ANCHOR_DRGS = {"480", "481", "482"}
EPISODE_WINDOW_DAYS = 30

# ---------------------------------------------------------------------------
# Provider dimension
# ---------------------------------------------------------------------------
# `setting` is the exec view's grouping key. `per_diem` / `per_visit` are what
# this generator prices lines at; they are not read back by the app.
#
# The spread across SNFs is the point of the whole feature. Memorial General's
# hospital-based Transitional Care Unit bills ~3x a freestanding SNF for
# clinically comparable patients — the same pattern as the CAH swing-bed panel
# in the reference figure. LOS is deliberately held comparable across all four
# SNFs so the gap is price, not utilisation, and cannot be waved away as "the
# TCU takes sicker patients".

PROVIDERS: List[Dict[str, Any]] = [
    {
        "ccn": "260001",
        "name": "Memorial General Hospital",
        "setting": "inpatient",
        "ownership": "system",
        "per_diem": None,
    },
    {
        "ccn": "140010",
        "name": "St. Anne's Regional Medical Center",
        "setting": "inpatient",
        "ownership": "competitor",
        "per_diem": None,
    },
    # --- SNF ---------------------------------------------------------------
    {
        "ccn": "265001",
        "name": "Memorial General Transitional Care Unit",
        "setting": "snf",
        "ownership": "hospital_based",
        "per_diem": 1725.0,
    },
    {
        "ccn": "265101",
        "name": "Springfield Health & Rehabilitation Center",
        "setting": "snf",
        "ownership": "freestanding",
        "per_diem": 545.0,
    },
    {
        "ccn": "265102",
        "name": "Prairie Meadows Care Center",
        "setting": "snf",
        "ownership": "freestanding",
        "per_diem": 598.0,
    },
    {
        "ccn": "265103",
        "name": "Cedar Ridge Nursing & Rehabilitation",
        "setting": "snf",
        "ownership": "freestanding",
        "per_diem": 642.0,
    },
    # --- IRF / HHA / hospice ------------------------------------------------
    {
        "ccn": "263025",
        "name": "Prairie View Rehabilitation Hospital",
        "setting": "irf",
        "ownership": "freestanding",
        "per_diem": 1685.0,
    },
    {
        "ccn": "267012",
        "name": "Memorial Home Health Services",
        "setting": "hha",
        "ownership": "system",
        "per_diem": 168.0,
    },
    {
        "ccn": "267045",
        "name": "HomeCare of Springfield",
        "setting": "hha",
        "ownership": "freestanding",
        "per_diem": 152.0,
    },
    {
        "ccn": "261500",
        "name": "Hope Hospice Services",
        "setting": "hospice",
        "ownership": "freestanding",
        "per_diem": 224.0,
    },
]

PROVIDER_BY_CCN = {p["ccn"]: p for p in PROVIDERS}

# Which SNF each SNF-disposition episode lands in, cycled in cohort order.
# Eleven SNF episodes → TCU 4, Springfield 3, Prairie Meadows 2, Cedar Ridge 2.
# Fixed rather than random so the demo's headline facility keeps a usable n.
SNF_CYCLE = [
    "265001", "265101", "265001", "265102", "265101",
    "265103", "265001", "265101", "265102", "265001", "265103",
]
HHA_CYCLE = ["267012", "267045"]

# Home-health agency names already present in referrals_{fin}.json, mapped onto
# the two agencies in the dimension so generated claims agree with the chart.
HHA_NAME_TO_CCN = {
    "Memorial Home Health Services": "267012",
    "Home Health Services of Springfield": "267012",
    "Home Health Care of Springfield": "267045",
    "HomeCare of Springfield": "267045",
}

# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------

DME_ITEMS = [
    ("E0143", "Folding walker, wheeled", 143.0),
    ("E0114", "Underarm crutches, pair", 95.0),
    ("E0163", "Commode chair, stationary", 180.0),
    ("E0260", "Hospital bed, semi-electric (rental)", 310.0),
    ("E0170", "Powered toilet seat lift", 265.0),
]

PT_EVAL = ("97161", 105.0)
PT_SESSION = ("97110", 85.0)

# TEAM target price per anchor MS-DRG. Blended across dispositions the way a
# real regional benchmark is: an uncomplicated discharge home lands under it,
# a freestanding SNF stay lands near it, and a hospital-based SNF stay or a
# readmission blows through it. That blend is what makes "savings" a real
# number rather than one we invented.
BASE_TARGET = {"480": 46000.0, "481": 37000.0, "482": 31000.0}
TARGET_AGE_PER_YEAR_OVER_75 = 120.0
TARGET_PER_COMORBIDITY = 850.0


def _rng(patient_id: int) -> random.Random:
    return random.Random(90210 + patient_id * 7919)


def _parse_dt(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    return datetime.fromisoformat(value).date()


def _age_at(birth: Optional[date], when: date) -> Optional[int]:
    if birth is None:
        return None
    years = when.year - birth.year
    if (when.month, when.day) < (birth.month, birth.day):
        years -= 1
    return years


def _setting_for_disposition(disposition: Optional[str]) -> str:
    """Collapse the cohort's five spellings of home-health onto one setting.

    Same substring approach both surfaces already use (see TODO.md — a real fix
    is a lookup on discharge_disposition_code).
    """
    d = (disposition or "").lower()
    if "skilled nursing" in d:
        return "snf"
    if "rehab" in d or "irf" in d:
        return "irf"
    if "hospice" in d:
        return "hospice"
    if "home health" in d or "hha" in d:
        return "hha"
    return "home"


class Line:
    """One generated claim line, in the shape of the existing feed CSVs."""

    __slots__ = (
        "bene_id", "clm_id", "fin", "from_dt", "thru_dt", "ccn", "npi",
        "clm_type", "hcpcs", "amount", "pos", "received_dt",
    )

    def __init__(self, **kw: Any) -> None:
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    def row(self) -> Dict[str, Any]:
        return {
            "BENE_ID": self.bene_id,
            "CLM_ID": self.clm_id,
            "FIN": self.fin,
            "CLM_FROM_DT": self.from_dt.isoformat(),
            "CLM_THRU_DT": self.thru_dt.isoformat(),
            "PRVDR_CCN": self.ccn or "",
            "PRVDR_NPI": self.npi or "",
            "CLM_TYPE": self.clm_type,
            "DRG_CD": "",
            "HCPCS_CD": self.hcpcs or "",
            "LINE_PMT_AMT": f"{self.amount:.2f}",
            "POS_CD": self.pos or "",
            "FILE_RECEIVED_DT": self.received_dt.isoformat(),
        }


def _received(rng: random.Random, thru: date) -> date:
    """Claims lag: payer feeds land 30-60 days after the service date."""
    return thru + timedelta(days=rng.randint(30, 60))


def _episode_lines(
    ep: Dict[str, Any], snf_index: int, hha_index: int, rng: random.Random
) -> List[Line]:
    """Post-acute + DME + outpatient-therapy lines for one anchor episode."""
    bene_id = ep["bene_id"]
    fin = ep["fin"]
    discharge = ep["discharge_date"]
    setting = ep["setting"]
    window_end = discharge + timedelta(days=EPISODE_WINDOW_DAYS)
    lines: List[Line] = []
    seq = 0

    def facility_line(ccn: str, start: date, days: int, pos: str) -> None:
        nonlocal seq
        seq += 1
        provider = PROVIDER_BY_CCN[ccn]
        end = min(start + timedelta(days=days - 1), window_end)
        billed_days = (end - start).days + 1
        lines.append(
            Line(
                bene_id=bene_id,
                clm_id=f"A{ccn}{fin}{seq:03d}",
                fin=fin,
                from_dt=start,
                thru_dt=end,
                ccn=ccn,
                npi=None,
                clm_type="I",
                hcpcs=None,
                amount=round(provider["per_diem"] * billed_days, 2),
                pos=pos,
                received_dt=_received(rng, end),
            )
        )

    def visit_line(ccn: str, when: date, hcpcs: str, amount: float, pos: str) -> None:
        nonlocal seq
        seq += 1
        lines.append(
            Line(
                bene_id=bene_id,
                clm_id=f"V{ccn}{fin}{seq:03d}",
                fin=fin,
                from_dt=when,
                thru_dt=when,
                ccn=ccn,
                npi=None,
                clm_type="I",
                hcpcs=hcpcs,
                amount=amount,
                pos=pos,
                received_dt=_received(rng, when),
            )
        )

    def supplier_line(prefix: str, npi: str, when: date, hcpcs: str,
                      amount: float, pos: str) -> None:
        nonlocal seq
        seq += 1
        lines.append(
            Line(
                bene_id=bene_id,
                clm_id=f"{prefix}{npi}{fin}{seq:03d}",
                fin=fin,
                from_dt=when,
                thru_dt=when,
                ccn=None,
                npi=npi,
                clm_type="P",
                hcpcs=hcpcs,
                amount=amount,
                pos=pos,
                received_dt=_received(rng, when),
            )
        )

    # --- the post-acute stay itself ----------------------------------------
    post_acute_days = 0
    if setting == "snf":
        ccn = ep["provider_ccn"] or SNF_CYCLE[snf_index % len(SNF_CYCLE)]
        # Held in one band across every SNF on purpose: the cost difference
        # between facilities has to be price, not length of stay.
        post_acute_days = rng.randint(14, 21)
        facility_line(ccn, discharge, post_acute_days, "31")
    elif setting == "irf":
        ccn = ep["provider_ccn"] or "263025"
        post_acute_days = rng.randint(10, 15)
        facility_line(ccn, discharge, post_acute_days, "61")
    elif setting == "hospice":
        ccn = ep["provider_ccn"] or "261500"
        post_acute_days = min(EPISODE_WINDOW_DAYS, rng.randint(18, 30))
        facility_line(ccn, discharge, post_acute_days, "34")
    elif setting == "hha":
        ccn = ep["provider_ccn"] or HHA_CYCLE[hha_index % len(HHA_CYCLE)]
        provider = PROVIDER_BY_CCN[ccn]
        visits = rng.randint(9, 16)
        for i in range(visits):
            when = discharge + timedelta(days=2 + int(i * 26 / max(visits, 1)))
            if when > window_end:
                break
            visit_line(ccn, when, "G0299", provider["per_diem"], "12")
        post_acute_days = visits

    ep["post_acute_days"] = post_acute_days
    ep["provider_ccn"] = ep["provider_ccn"] or (
        lines[0].ccn if lines and lines[0].ccn else None
    )

    # --- DME -----------------------------------------------------------------
    # Everyone going home under their own steam needs equipment; facility
    # patients need less of it because the facility supplies the gear.
    dme_npi = "1546302977"
    n_dme = rng.randint(1, 3) if setting in ("home", "hha") else rng.randint(0, 1)
    for item_code, _label, price in rng.sample(DME_ITEMS, k=min(n_dme, len(DME_ITEMS))):
        when = discharge + timedelta(days=rng.randint(0, 3))
        supplier_line("D", dme_npi, when, item_code, price, "12")

    # --- outpatient therapy --------------------------------------------------
    # Home patients do their rehab as outpatient visits; facility patients did
    # most of theirs inside the per-diem, so they get a shorter tail.
    pt_npi = "1730289455"
    if setting in ("home", "hha"):
        sessions = rng.randint(6, 14)
        start_offset = 5
    elif setting in ("snf", "irf"):
        sessions = rng.randint(0, 4)
        start_offset = 22
    else:
        sessions = 0
        start_offset = 0
    if sessions:
        eval_day = discharge + timedelta(days=start_offset)
        if eval_day <= window_end:
            supplier_line("T", pt_npi, eval_day, PT_EVAL[0], PT_EVAL[1], "11")
        for i in range(sessions):
            when = discharge + timedelta(days=start_offset + 2 + i * 2)
            if when > window_end:
                break
            supplier_line("T", pt_npi, when, PT_SESSION[0], PT_SESSION[1], "11")

    return lines


def _target_price(drg: str, age: Optional[int], comorbidities: int) -> float:
    base = BASE_TARGET.get(drg, BASE_TARGET["481"])
    if age:
        base += max(0, age - 75) * TARGET_AGE_PER_YEAR_OVER_75
    base += comorbidities * TARGET_PER_COMORBIDITY
    return round(base, 2)


def _read_episode(patient_dir: Path) -> Optional[Dict[str, Any]]:
    """Pull one anchor SHFFT episode out of a patient's source export."""
    reg_path = patient_dir / "registration.json"
    hist_path = patient_dir / "encounter_history.json"
    if not reg_path.exists() or not hist_path.exists():
        return None

    reg = json.loads(reg_path.read_text(encoding="utf-8"))
    hist = json.loads(hist_path.read_text(encoding="utf-8"))

    anchor = next(
        (
            e
            for e in hist.get("encounters", [])
            if e.get("ms_drg") in ANCHOR_DRGS
            and len(e.get("fin", "")) == 6
            and e["fin"].startswith("00")
        ),
        None,
    )
    if anchor is None:
        return None

    discharge = _parse_dt(anchor.get("discharge_datetime"))
    if discharge is None:
        return None

    problems = json.loads((patient_dir / "problem_list.json").read_text("utf-8")) \
        if (patient_dir / "problem_list.json").exists() else {"problems": []}
    comorbidities = sum(
        1 for p in problems.get("problems", []) if p.get("status") == "Active"
    )

    disposition = anchor.get("discharge_disposition")
    setting = _setting_for_disposition(disposition)

    # Honour an existing post-acute referral's named facility when the source
    # data has one, so generated claims agree with referrals_{fin}.json.
    provider_ccn: Optional[str] = None
    ref_path = patient_dir / f"referrals_{anchor['fin']}.json"
    if ref_path.exists():
        for ref in json.loads(ref_path.read_text("utf-8")).get("referrals", []):
            name = ref.get("referred_to") or ""
            if setting == "hha" and name in HHA_NAME_TO_CCN:
                provider_ccn = HHA_NAME_TO_CCN[name]
            elif setting == "irf" and "Prairie View" in name:
                provider_ccn = "263025"
            elif setting == "hospice" and "Hope Hospice" in name:
                provider_ccn = "261500"

    birth = date.fromisoformat(reg["birth_date"]) if reg.get("birth_date") else None
    return {
        "patient_id": int(patient_dir.name),
        "bene_id": reg.get("payer_primary", {}).get("subscriber_id"),
        "fin": anchor["fin"],
        "ms_drg": anchor["ms_drg"],
        "discharge_date": discharge,
        "disposition": disposition,
        "setting": setting,
        "provider_ccn": provider_ccn,
        "age": _age_at(birth, discharge),
        "comorbidities": comorbidities,
        "post_acute_days": 0,
    }


def generate() -> None:
    FEEDS_DIR.mkdir(parents=True, exist_ok=True)

    episodes: List[Dict[str, Any]] = []
    for patient_dir in sorted(
        (p for p in DATA_ROOT.iterdir() if p.is_dir() and p.name.isdigit()),
        key=lambda p: int(p.name),
    ):
        ep = _read_episode(patient_dir)
        if ep is not None:
            episodes.append(ep)

    all_lines: List[Line] = []
    snf_index = 0
    hha_index = 0
    for ep in episodes:
        rng = _rng(ep["patient_id"])
        all_lines.extend(_episode_lines(ep, snf_index, hha_index, rng))
        if ep["setting"] == "snf":
            snf_index += 1
        elif ep["setting"] == "hha" and ep["provider_ccn"] is None:
            hha_index += 1

    # --- provider dimension --------------------------------------------------
    provider_path = FEEDS_DIR / "provider_facility.csv"
    with provider_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["CCN", "NAME", "SETTING", "OWNERSHIP"])
        w.writeheader()
        for p in PROVIDERS:
            w.writerow(
                {
                    "CCN": p["ccn"],
                    "NAME": p["name"],
                    "SETTING": p["setting"],
                    "OWNERSHIP": p["ownership"],
                }
            )

    # --- claim lines ---------------------------------------------------------
    claims_path = FEEDS_DIR / "post_acute_claims.csv"
    fieldnames = [
        "BENE_ID", "CLM_ID", "FIN", "CLM_FROM_DT", "CLM_THRU_DT", "PRVDR_CCN",
        "PRVDR_NPI", "CLM_TYPE", "DRG_CD", "HCPCS_CD", "LINE_PMT_AMT", "POS_CD",
        "FILE_RECEIVED_DT",
    ]
    with claims_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for line in all_lines:
            w.writerow(line.row())

    # --- TEAM target prices --------------------------------------------------
    target_path = FEEDS_DIR / "episode_target_price.csv"
    with target_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "FIN", "PATIENT_ID", "MS_DRG", "TARGET_PRICE", "AGE",
                "COMORBIDITY_COUNT", "POST_ACUTE_CCN", "POST_ACUTE_SETTING",
                "POST_ACUTE_DAYS",
            ],
        )
        w.writeheader()
        for ep in episodes:
            w.writerow(
                {
                    "FIN": ep["fin"],
                    "PATIENT_ID": ep["patient_id"],
                    "MS_DRG": ep["ms_drg"],
                    "TARGET_PRICE": _target_price(
                        ep["ms_drg"], ep["age"], ep["comorbidities"]
                    ),
                    "AGE": ep["age"] if ep["age"] is not None else "",
                    "COMORBIDITY_COUNT": ep["comorbidities"],
                    "POST_ACUTE_CCN": ep["provider_ccn"] or "",
                    "POST_ACUTE_SETTING": ep["setting"],
                    "POST_ACUTE_DAYS": ep["post_acute_days"],
                }
            )

    total = sum(line.amount for line in all_lines)
    by_setting: Dict[str, int] = {}
    for ep in episodes:
        by_setting[ep["setting"]] = by_setting.get(ep["setting"], 0) + 1
    print(f"Wrote {provider_path.relative_to(REPO_ROOT)} ({len(PROVIDERS)} providers)")
    print(f"Wrote {claims_path.relative_to(REPO_ROOT)} ({len(all_lines)} lines,"
          f" ${total:,.0f} paid)")
    print(f"Wrote {target_path.relative_to(REPO_ROOT)} ({len(episodes)} episodes)")
    for setting, n in sorted(by_setting.items(), key=lambda kv: -kv[1]):
        print(f"  {setting}: {n} episodes")


if __name__ == "__main__":
    generate()
