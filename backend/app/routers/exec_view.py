"""GET /api/exec/* — executive view: episode economics by care setting (D13/D15).

The care-team surface answers "who do I call next". This one answers "where is
the money going, and which patients are driving it" — the question a CFO or VP
of care transitions asks before adopting the tool.

Rows are **post-acute destination**, not inpatient facility. There is one
hospital in this cohort, and under TEAM the 30 days after discharge are what a
health system can actually move, so where the patient went is the lever.

Three rules run through every number here:

  as-of      Spend counts a claim line only once its service period has closed
             on or before the as-of clock (clm_thru_dt <= as_of), so an episode
             still inside its 30-day window reports spend-to-date. Everything
             aggregates from v_episode_claim with that one filter — there is no
             second, pre-aggregated path that could drift.

  closed     Savings-vs-target and readmission rate are reported over episodes
             whose 30-day window has closed. Averaging a partial episode against
             a full-episode target would understate spend on every in-flight row.
             Facility rows carry both counts so the denominator is always visible.

  small n    A 50-episode cohort spreads thin across nine destinations. Deltas
             are suppressed below MIN_N_FOR_DELTA closed episodes rather than
             rendered at n=1. Suppression is reported (`delta_suppressed`), not
             silent.

Money is Medicare **paid**, never charged. The cohort carries both and they
differ by ~45%; charges do not belong on an executive screen.
"""

from __future__ import annotations

from datetime import date, timedelta
from statistics import median
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..auth import get_current_user
from ..clock import get_as_of
from ..db import get_connection

router = APIRouter(prefix="/api/exec", tags=["exec"])

EPISODE_WINDOW_DAYS = 30

# Below this many closed episodes a facility's deltas are not shown. Four of the
# nine destinations in this cohort sit under it — showing "+$12k vs peers" off
# n=1 is how a dashboard loses an executive's trust in the first meeting.
MIN_N_FOR_DELTA = 5

# A facility is flagged as a cost outlier when its cost per post-acute day runs
# this far above the median freestanding provider in the same setting.
OUTLIER_PRICE_RATIO = 1.5

# An episode is flagged when it exceeds the median episode in its own setting by
# this much — peer-relative, so a SNF episode is judged against SNF episodes.
OUTLIER_EPISODE_RATIO = 1.25

POST_ACUTE_CATEGORIES = ("snf", "irf", "hha", "hospice")

CATEGORY_LABELS: Dict[str, str] = {
    "anchor_inpatient": "Anchor inpatient",
    "readmission": "Readmission",
    "snf": "SNF",
    "irf": "Inpatient rehab",
    "hha": "Home health",
    "hospice": "Hospice",
    "outpatient_therapy": "Outpatient therapy",
    "dme": "DME",
    "professional": "Professional",
}

SETTING_LABELS: Dict[str, str] = {
    "snf": "Skilled nursing",
    "irf": "Inpatient rehab",
    "hha": "Home health",
    "hospice": "Hospice",
    "home": "Home / self-care",
}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class KpiSummary(BaseModel):
    episodes: int
    closed_episodes: int
    in_flight_episodes: int
    total_spend: float
    spend_to_date: float
    avg_spend_closed: Optional[float]
    avg_target_closed: Optional[float]
    net_savings_closed: Optional[float]
    savings_rate_closed: Optional[float]
    episodes_over_target: int
    avg_ip_los: Optional[float]
    readmit_rate_closed: Optional[float]
    pct_discharged_home: Optional[float]
    post_acute_share: Optional[float]


class FacilityRow(BaseModel):
    facility_key: str
    facility_name: str
    setting: str
    setting_label: str
    ownership: str
    episodes: int
    closed_episodes: int
    total_spend: float
    avg_spend: Optional[float]
    avg_target: Optional[float]
    avg_variance: Optional[float]
    post_acute_spend: float
    post_acute_days: int
    cost_per_post_acute_day: Optional[float]
    peer_cost_per_day: Optional[float]
    price_ratio: Optional[float]
    avg_ip_los: Optional[float]
    readmit_rate: Optional[float]
    delta_suppressed: bool
    is_price_outlier: bool


class EpisodeCostRow(BaseModel):
    fin: str
    patient_id: int
    mrn: str
    patient_name: str
    age: Optional[int]
    ms_drg: Optional[str]
    discharge_date: Optional[str]
    window_end: Optional[str]
    status: str
    setting: str
    facility_key: str
    facility_name: str
    comorbidity_count: Optional[int]
    length_of_stay_days: Optional[int]
    post_acute_days: Optional[int]
    target_price: Optional[float]
    actual_spend: float
    variance: Optional[float]
    variance_pct: Optional[float]
    target_consumed_pct: Optional[float]
    peer_median: Optional[float]
    is_outlier: bool
    had_readmission: bool
    drivers: List[Dict[str, Any]]


class FacilityDetail(BaseModel):
    meta: Dict[str, Any]
    facility: FacilityRow
    episodes: List[EpisodeCostRow]


class FacilityResponse(BaseModel):
    meta: Dict[str, Any]
    facilities: List[FacilityRow]


class SummaryResponse(BaseModel):
    meta: Dict[str, Any]
    kpis: KpiSummary
    opportunity: Optional[Dict[str, Any]]


class OutlierResponse(BaseModel):
    meta: Dict[str, Any]
    episodes: List[EpisodeCostRow]


class CategoryRow(BaseModel):
    category: str
    label: str
    cohort_per_episode: float
    selected_per_episode: float


class CategoryResponse(BaseModel):
    meta: Dict[str, Any]
    selected_key: str
    selected_label: str
    categories: List[CategoryRow]


# ---------------------------------------------------------------------------
# Aggregation — one path, one as-of filter
# ---------------------------------------------------------------------------


def _episode_status(
    discharge: Optional[str], window_end: Optional[str], as_of: date
) -> str:
    if not window_end:
        return "unknown"
    if date.fromisoformat(window_end) <= as_of:
        return "closed"
    if discharge and date.fromisoformat(discharge) > as_of:
        return "predischarge"
    return "in_flight"


def _spend_by_episode(conn, as_of: date) -> Dict[str, Dict[str, Dict[str, float]]]:
    """fin → {category: {paid, days}}. A line counts once its service period closed.

    Days are counted off the same filtered lines as the dollars, never off
    episode_target_price.post_acute_days. That column describes the whole
    generated stay, so dividing as-of-filtered spend by it would understate
    cost per day on every in-flight episode — a hospital-based SNF billing
    $1,725/day would render at $874 and the price story would vanish.

    A facility stay is one line spanning its dates; a home-health visit is one
    line on one date. Summing (thru - from + 1) therefore yields covered days
    for the former and visit counts for the latter, which is what each setting
    should be costed per.
    """
    rows = conn.execute(
        """
        SELECT episode_fin,
               category,
               SUM(line_pmt_amt)                                         AS amt,
               SUM(julianday(clm_thru_dt) - julianday(clm_from_dt) + 1)  AS days
        FROM v_episode_claim
        WHERE line_pmt_amt IS NOT NULL
          AND date(clm_thru_dt) <= date(?)
        GROUP BY episode_fin, category
        """,
        (as_of.isoformat(),),
    ).fetchall()
    out: Dict[str, Dict[str, Dict[str, float]]] = {}
    for r in rows:
        out.setdefault(r["episode_fin"], {})[r["category"]] = {
            "paid": float(r["amt"] or 0.0),
            "days": float(r["days"] or 0.0),
        }
    return out


def _episodes(conn, as_of: date) -> List[Dict[str, Any]]:
    """Every anchor episode with its dimensions and as-of-filtered spend."""
    rows = conn.execute(
        """
        SELECT patient_id, fin, mrn, patient_name, ms_drg, admit_date,
               discharge_date, window_end, length_of_stay_days,
               discharge_disposition, target_price, age, comorbidity_count,
               post_acute_days, setting, facility_key, facility_name, ownership
        FROM v_episode_econ
        """
    ).fetchall()
    spend = _spend_by_episode(conn, as_of)

    episodes: List[Dict[str, Any]] = []
    for r in rows:
        buckets = spend.get(r["fin"], {})
        by_cat = {c: b["paid"] for c, b in buckets.items()}
        actual = sum(by_cat.values())
        ep = dict(r)
        ep["by_category"] = by_cat
        ep["actual_spend"] = round(actual, 2)
        ep["status"] = _episode_status(r["discharge_date"], r["window_end"], as_of)
        ep["had_readmission"] = by_cat.get("readmission", 0) > 0
        ep["post_acute_spend"] = round(
            sum(by_cat.get(c, 0.0) for c in POST_ACUTE_CATEGORIES), 2
        )
        # Counted days, matched to counted dollars — see _spend_by_episode.
        ep["post_acute_days_counted"] = int(
            sum(buckets.get(c, {}).get("days", 0.0) for c in POST_ACUTE_CATEGORIES)
        )
        target = r["target_price"]
        # Variance is defined only once the 30-day window has closed. Scoring a
        # partial episode against a full-episode target reads as enormous
        # savings — a patient still on the table shows -$52k "saved" — which is
        # exactly backwards. In-flight episodes get target_consumed_pct instead:
        # how much of the target is already spent, which is a real early warning.
        ep["variance"] = (
            round(actual - target, 2) if target and ep["status"] == "closed" else None
        )
        ep["target_consumed_pct"] = (
            round(100.0 * actual / target, 1) if target and actual else None
        )
        episodes.append(ep)
    return episodes


def _org_name(conn, org_id: str) -> str:
    row = conn.execute(
        "SELECT name FROM app.organization WHERE org_id = ?", (org_id,)
    ).fetchone()
    return row["name"] if row else org_id


def _meta(
    as_of: date, mode: str, episodes: List[Dict[str, Any]], org_name: str = ""
) -> Dict[str, Any]:
    closed = [e for e in episodes if e["status"] == "closed"]
    return {
        "as_of": as_of.isoformat(),
        "as_of_mode": mode,
        "org_name": org_name,
        "episodes": len(episodes),
        "closed_episodes": len(closed),
        "in_flight_episodes": len(episodes) - len(closed),
        "min_n_for_delta": MIN_N_FOR_DELTA,
        "basis": "medicare_paid",
        "window_days": EPISODE_WINDOW_DAYS,
        # Real payer feeds land 30-60 days after service, so a live deployment
        # would always trail finance. Surfaced rather than hidden.
        "claims_lag_note": (
            "Spend counts claim lines whose service period closed on or before "
            "the as-of date. Payer feeds in this cohort arrive 30-60 days after "
            "service."
        ),
    }


def _safe_mean(values: List[float]) -> Optional[float]:
    return round(sum(values) / len(values), 2) if values else None


# ---------------------------------------------------------------------------
# Facility rollup
# ---------------------------------------------------------------------------


def _facility_rows(episodes: List[Dict[str, Any]]) -> List[FacilityRow]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for e in episodes:
        groups.setdefault(e["facility_key"], []).append(e)

    # Peer price benchmark: the median cost per post-acute day among
    # freestanding providers in the same setting. Freestanding only, so a
    # hospital-based unit cannot inflate the very benchmark it is judged
    # against.
    per_day_by_setting: Dict[str, List[float]] = {}
    for key, members in groups.items():
        setting = members[0]["setting"]
        if setting == "home" or members[0]["ownership"] != "freestanding":
            continue
        days = sum(m["post_acute_days_counted"] for m in members)
        spend = sum(m["post_acute_spend"] for m in members)
        if days > 0:
            per_day_by_setting.setdefault(setting, []).append(spend / days)
    peer_per_day = {s: median(v) for s, v in per_day_by_setting.items() if v}

    rows: List[FacilityRow] = []
    for key, members in groups.items():
        first = members[0]
        closed = [m for m in members if m["status"] == "closed"]
        days = sum(m["post_acute_days_counted"] for m in members)
        pa_spend = sum(m["post_acute_spend"] for m in members)
        per_day = round(pa_spend / days, 2) if days else None
        peer = peer_per_day.get(first["setting"])
        ratio = round(per_day / peer, 2) if per_day and peer else None
        enough = len(closed) >= MIN_N_FOR_DELTA
        los = [m["length_of_stay_days"] for m in members if m["length_of_stay_days"]]

        rows.append(
            FacilityRow(
                facility_key=key,
                facility_name=first["facility_name"],
                setting=first["setting"],
                setting_label=SETTING_LABELS.get(first["setting"], first["setting"]),
                ownership=first["ownership"],
                episodes=len(members),
                closed_episodes=len(closed),
                total_spend=round(sum(m["actual_spend"] for m in members), 2),
                avg_spend=_safe_mean([m["actual_spend"] for m in closed]),
                avg_target=_safe_mean(
                    [m["target_price"] for m in closed if m["target_price"]]
                ),
                avg_variance=_safe_mean(
                    [m["variance"] for m in closed if m["variance"] is not None]
                ),
                post_acute_spend=round(pa_spend, 2),
                post_acute_days=days,
                cost_per_post_acute_day=per_day,
                peer_cost_per_day=round(peer, 2) if peer else None,
                price_ratio=ratio,
                avg_ip_los=round(sum(los) / len(los), 1) if los else None,
                readmit_rate=(
                    round(
                        100.0 * sum(1 for m in closed if m["had_readmission"]) / len(closed),
                        1,
                    )
                    if closed
                    else None
                ),
                delta_suppressed=not enough,
                # Price outliers are judged on cost per day, which is independent
                # of how many episodes the facility has — so this flag stands
                # even where n is too small to show a savings delta.
                is_price_outlier=bool(ratio and ratio >= OUTLIER_PRICE_RATIO),
            )
        )

    rows.sort(key=lambda r: r.total_spend, reverse=True)
    return rows


def _peer_medians(episodes: List[Dict[str, Any]]) -> Dict[str, float]:
    """Median actual spend per setting — the yardstick an episode is judged by."""
    by_setting: Dict[str, List[float]] = {}
    for e in episodes:
        by_setting.setdefault(e["setting"], []).append(e["actual_spend"])
    return {s: median(v) for s, v in by_setting.items() if v}


def _drivers(
    episode: Dict[str, Any], setting_category_medians: Dict[str, Dict[str, float]]
) -> List[Dict[str, Any]]:
    """Decompose an episode's excess over its peers into cost categories.

    "$19k over" is not actionable. "61% of the excess is SNF days, 32% is the
    readmission" tells a navigator what to change.
    """
    medians = setting_category_medians.get(episode["setting"], {})
    deltas = []
    for category, amount in episode["by_category"].items():
        delta = amount - medians.get(category, 0.0)
        if delta > 0:
            deltas.append((category, delta, amount))

    total_excess = sum(d[1] for d in deltas)
    if total_excess <= 0:
        return []

    deltas.sort(key=lambda d: d[1], reverse=True)
    return [
        {
            "category": category,
            "label": CATEGORY_LABELS.get(category, category),
            "amount": round(amount, 2),
            "excess": round(delta, 2),
            "share": round(100.0 * delta / total_excess, 1),
        }
        for category, delta, amount in deltas[:4]
    ]


def _category_medians(episodes: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    grouped: Dict[str, Dict[str, List[float]]] = {}
    for e in episodes:
        bucket = grouped.setdefault(e["setting"], {})
        for category in CATEGORY_LABELS:
            bucket.setdefault(category, []).append(e["by_category"].get(category, 0.0))
    return {
        setting: {c: median(v) for c, v in cats.items()}
        for setting, cats in grouped.items()
    }


def _to_episode_row(
    e: Dict[str, Any],
    peer_medians: Dict[str, float],
    category_medians: Dict[str, Dict[str, float]],
) -> EpisodeCostRow:
    peer = peer_medians.get(e["setting"])
    target = e["target_price"]
    return EpisodeCostRow(
        fin=e["fin"],
        patient_id=e["patient_id"],
        mrn=e["mrn"],
        patient_name=e["patient_name"],
        age=e["age"],
        ms_drg=e["ms_drg"],
        discharge_date=e["discharge_date"],
        window_end=e["window_end"],
        status=e["status"],
        setting=e["setting"],
        facility_key=e["facility_key"],
        facility_name=e["facility_name"],
        comorbidity_count=e["comorbidity_count"],
        length_of_stay_days=e["length_of_stay_days"],
        post_acute_days=e["post_acute_days_counted"],
        target_price=target,
        actual_spend=e["actual_spend"],
        variance=e["variance"],
        variance_pct=(
            round(100.0 * e["variance"] / target, 1) if target and e["variance"] else None
        ),
        target_consumed_pct=e["target_consumed_pct"],
        peer_median=round(peer, 2) if peer else None,
        is_outlier=bool(peer and e["actual_spend"] > peer * OUTLIER_EPISODE_RATIO),
        had_readmission=e["had_readmission"],
        drivers=_drivers(e, category_medians),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/summary", response_model=SummaryResponse)
def exec_summary(user: Dict[str, str] = Depends(get_current_user)) -> SummaryResponse:
    """Board-level KPI strip plus the single largest savings opportunity."""
    as_of, mode = get_as_of()
    conn = get_connection()
    try:
        episodes = _episodes(conn, as_of)
        org_name = _org_name(conn, user["org_id"])
    finally:
        conn.close()

    closed = [e for e in episodes if e["status"] == "closed"]
    total_spend = sum(e["actual_spend"] for e in episodes)
    post_acute = sum(e["post_acute_spend"] for e in episodes)
    variances = [e["variance"] for e in closed if e["variance"] is not None]
    targets = [e["target_price"] for e in closed if e["target_price"]]
    los = [e["length_of_stay_days"] for e in episodes if e["length_of_stay_days"]]
    home_like = sum(1 for e in episodes if e["setting"] in ("home", "hha"))

    kpis = KpiSummary(
        episodes=len(episodes),
        closed_episodes=len(closed),
        in_flight_episodes=len(episodes) - len(closed),
        total_spend=round(total_spend, 2),
        spend_to_date=round(total_spend, 2),
        avg_spend_closed=_safe_mean([e["actual_spend"] for e in closed]),
        avg_target_closed=_safe_mean(targets),
        net_savings_closed=round(sum(-v for v in variances), 2) if variances else None,
        savings_rate_closed=(
            round(100.0 * sum(-v for v in variances) / sum(targets), 1)
            if variances and sum(targets)
            else None
        ),
        episodes_over_target=sum(1 for v in variances if v > 0),
        avg_ip_los=round(sum(los) / len(los), 1) if los else None,
        readmit_rate_closed=(
            round(100.0 * sum(1 for e in closed if e["had_readmission"]) / len(closed), 1)
            if closed
            else None
        ),
        pct_discharged_home=(
            round(100.0 * home_like / len(episodes), 1) if episodes else None
        ),
        post_acute_share=(
            round(100.0 * post_acute / total_spend, 1) if total_spend else None
        ),
    )

    return SummaryResponse(
        meta=_meta(as_of, mode, episodes, org_name),
        kpis=kpis,
        opportunity=_opportunity(episodes),
    )


def _opportunity(episodes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The named, quantified 'do this' — the reason an exec screen gets used.

    Finds the setting's most overpriced provider by cost per post-acute day and
    prices out what those same days would have cost at the peer median. That is
    a contracting/steerage decision, not a care-quality one, which is why it is
    computed from price per day and not from total spend.
    """
    rows = _facility_rows(episodes)
    candidates = [
        r
        for r in rows
        if r.is_price_outlier and r.cost_per_post_acute_day and r.peer_cost_per_day
    ]
    if not candidates:
        return None

    worst = max(candidates, key=lambda r: r.total_spend)
    avoidable = (worst.cost_per_post_acute_day - worst.peer_cost_per_day) * worst.post_acute_days
    per_episode = avoidable / worst.episodes if worst.episodes else 0.0
    return {
        "facility_key": worst.facility_key,
        "facility_name": worst.facility_name,
        "setting_label": worst.setting_label,
        "episodes": worst.episodes,
        "post_acute_days": worst.post_acute_days,
        "cost_per_day": worst.cost_per_post_acute_day,
        "peer_cost_per_day": worst.peer_cost_per_day,
        "price_ratio": worst.price_ratio,
        "avoidable_spend": round(avoidable, 2),
        "avoidable_per_episode": round(per_episode, 2),
        "headline": (
            f"{worst.facility_name} bills "
            f"{worst.price_ratio:.1f}x the freestanding median for comparable "
            f"{worst.setting_label.lower()} days"
        ),
        # The per-episode figure and the total both render beside this sentence
        # in the closing card, so the sentence carries the action, not a repeat
        # of the arithmetic.
        "action": (
            f"Steering these {worst.episodes} episodes to a freestanding provider "
            f"at the peer rate would have avoided ${avoidable:,.0f} — with no "
            f"change in length of stay, only in where the days were delivered."
        ),
    }


@router.get("/facilities", response_model=FacilityResponse)
def exec_facilities(
    user: Dict[str, str] = Depends(get_current_user),
) -> FacilityResponse:
    """One row per post-acute destination — the main executive table."""
    as_of, mode = get_as_of()
    conn = get_connection()
    try:
        episodes = _episodes(conn, as_of)
        org_name = _org_name(conn, user["org_id"])
    finally:
        conn.close()
    return FacilityResponse(
        meta=_meta(as_of, mode, episodes, org_name), facilities=_facility_rows(episodes)
    )


@router.get("/facilities/{facility_key}/episodes", response_model=FacilityDetail)
def exec_facility_episodes(
    facility_key: str, user: Dict[str, str] = Depends(get_current_user)
) -> FacilityDetail:
    """Drill-down: the individual episodes behind one facility's number."""
    as_of, mode = get_as_of()
    conn = get_connection()
    try:
        episodes = _episodes(conn, as_of)
        org_name = _org_name(conn, user["org_id"])
    finally:
        conn.close()

    row = next((r for r in _facility_rows(episodes) if r.facility_key == facility_key), None)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown facility {facility_key!r}")

    peers = _peer_medians(episodes)
    cat_medians = _category_medians(episodes)
    members = [
        _to_episode_row(e, peers, cat_medians)
        for e in episodes
        if e["facility_key"] == facility_key
    ]
    members.sort(key=lambda m: m.variance if m.variance is not None else 0, reverse=True)

    return FacilityDetail(meta=_meta(as_of, mode, episodes, org_name), facility=row, episodes=members)


@router.get("/outliers", response_model=OutlierResponse)
def exec_outliers(
    limit: int = Query(10, ge=1, le=50),
    user: Dict[str, str] = Depends(get_current_user),
) -> OutlierResponse:
    """Episodes running furthest over their TEAM target, with cost drivers."""
    as_of, mode = get_as_of()
    conn = get_connection()
    try:
        episodes = _episodes(conn, as_of)
        org_name = _org_name(conn, user["org_id"])
    finally:
        conn.close()

    peers = _peer_medians(episodes)
    cat_medians = _category_medians(episodes)
    rows = [_to_episode_row(e, peers, cat_medians) for e in episodes]
    over = [r for r in rows if r.variance is not None and r.variance > 0]
    over.sort(key=lambda r: r.variance or 0, reverse=True)

    return OutlierResponse(meta=_meta(as_of, mode, episodes, org_name), episodes=over[:limit])


@router.get("/cost-categories", response_model=CategoryResponse)
def exec_cost_categories(
    facility: Optional[str] = Query(None),
    user: Dict[str, str] = Depends(get_current_user),
) -> CategoryResponse:
    """Per-episode spend by cost category: one destination against the cohort.

    The benchmark is this cohort's own per-episode average, not an external
    regional rate — there is no region in the synthetic data, and labelling an
    internal average as a regional benchmark would be a lie an actuary would
    catch immediately.
    """
    as_of, mode = get_as_of()
    conn = get_connection()
    try:
        episodes = _episodes(conn, as_of)
        org_name = _org_name(conn, user["org_id"])
    finally:
        conn.close()

    if not episodes:
        raise HTTPException(status_code=404, detail="No episodes")

    # Default to the facility with the most total spend among the flagged price
    # outliers, so the panel opens on something worth looking at.
    rows = _facility_rows(episodes)
    if facility is None:
        flagged = [r for r in rows if r.is_price_outlier]
        facility = (flagged or rows)[0].facility_key

    selected = [e for e in episodes if e["facility_key"] == facility]
    if not selected:
        raise HTTPException(status_code=404, detail=f"Unknown facility {facility!r}")
    selected_name = selected[0]["facility_name"]

    categories: List[CategoryRow] = []
    for category, label in CATEGORY_LABELS.items():
        cohort_total = sum(e["by_category"].get(category, 0.0) for e in episodes)
        sel_total = sum(e["by_category"].get(category, 0.0) for e in selected)
        cohort_avg = cohort_total / len(episodes)
        sel_avg = sel_total / len(selected)
        if cohort_avg == 0 and sel_avg == 0:
            continue
        categories.append(
            CategoryRow(
                category=category,
                label=label,
                cohort_per_episode=round(cohort_avg, 2),
                selected_per_episode=round(sel_avg, 2),
            )
        )

    return CategoryResponse(
        meta=_meta(as_of, mode, episodes, org_name),
        selected_key=facility,
        selected_label=selected_name,
        categories=categories,
    )
