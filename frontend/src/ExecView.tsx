/**
 * Executive view (D13 / D15) — episode economics by post-acute destination.
 *
 * Reads top to bottom as an argument, not a pile of charts:
 *
 *   1. KPI strip          what the 30-day episode book looks like
 *   2. Opportunity card   the one named, quantified thing to go do
 *   3. Facility table     where the money goes, by destination
 *   4. Drill-down         the individual episodes behind one facility
 *   5. Cost categories    which category is actually out of line (the acuity rebuttal)
 *   6. Outliers           the patients driving the overage, with cost drivers
 *
 * Chart conventions follow the project's dataviz rules and the palette below is
 * validated (lightness band, chroma floor, CVD separation, contrast) rather than
 * eyeballed — the brand's forest/clay tokens are too dark and too low-chroma to
 * be marks, and forest↔clay fails deuteranopia outright.
 *
 *   magnitude (in-cell bars)  one hue, every bar the same colour; length is the
 *                             encoding. Never darker-where-bigger — that would
 *                             burn the colour channel re-stating the bar length.
 *   polarity (variance)       diverging warm/cool with a neutral midpoint, and
 *                             always a sign and a word too, never colour alone.
 *   identity (2 series)       categorical pair, legend always present.
 */
import { useEffect, useState } from "react";
import {
  CostCategoryResponse,
  EpisodeCostRow,
  ExecSummaryResponse,
  FacilityDetailResponse,
  FacilityRow,
  OutlierResponse,
  fetchCostCategories,
  fetchExecSummary,
  fetchFacilities,
  fetchFacilityEpisodes,
  fetchOutliers,
} from "./api";
import { ViewMeta } from "./viewState";

// --- validated palette ------------------------------------------------------
// node scripts/validate_palette.js "#0f7fb2,#cf7434" --mode light  → ALL PASS
// node scripts/validate_palette.js "#c4472e,#0e8f7f" --mode light  → ALL PASS
const MAGNITUDE = "#0f7fb2"; // single hue for every in-cell bar
const SERIES_SELECTED = "#cf7434"; // categorical slot 1 — the facility in focus
const SERIES_COHORT = "#0f7fb2"; // categorical slot 2 — the benchmark
const OVER = "#c4472e"; // diverging warm pole — over target
const UNDER = "#0e8f7f"; // diverging cool pole — under target
// Ordinal ramp for driver segments — ordered parts of one quantity, so one hue
// stepped by rank, not four identities.
// node scripts/validate_palette.js "#0a5678,#0f7fb2,#4295c2,#79b4d3" --ordinal → ALL PASS
const DRIVER_RAMP = ["#0a5678", "#0f7fb2", "#4295c2", "#79b4d3"];

function fmtMoney(n: number | null | undefined): string {
  if (n == null) return "—";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `$${Math.round(n / 1000)}K`;
  return `$${Math.round(n)}`;
}

function fmtMoneyFull(n: number | null | undefined): string {
  if (n == null) return "—";
  return `$${Math.round(n).toLocaleString()}`;
}

function fmtSigned(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${fmtMoney(Math.abs(n))}`;
}

function fmtPct(n: number | null | undefined, digits = 0): string {
  return n == null ? "—" : `${n.toFixed(digits)}%`;
}

/**
 * In-cell magnitude bar. 4px rounded data-end, anchored to the baseline, with
 * the value beside it — the number is always readable without the bar, so the
 * bar is pure at-a-glance ranking.
 */
function CellBar({
  value,
  max,
  label,
  title,
}: {
  value: number | null;
  max: number;
  label: string;
  title?: string;
}) {
  const pct = value != null && max > 0 ? Math.max(2, (value / max) * 100) : 0;
  return (
    <div className="cell-bar" title={title}>
      <div className="cell-bar-track">
        <div
          className="cell-bar-fill"
          style={{ width: `${pct}%`, background: MAGNITUDE }}
        />
      </div>
      <span className="cell-bar-label">{label}</span>
    </div>
  );
}

/**
 * Variance chip: diverging colour plus a sign and a word, never colour alone.
 *
 * Below the confidence threshold the number is still shown, but de-emphasised
 * and stamped with its n. Withholding it entirely — the first cut — blanked
 * seven of nine rows in this cohort and gutted the table's most important
 * column; a greyed figure the reader can see is n=2 is both more useful and
 * just as honest.
 */
function VarianceChip({
  value,
  suppressed,
  minN,
  n,
}: {
  value: number | null;
  suppressed?: boolean;
  minN?: number;
  n?: number;
}) {
  if (value == null) {
    return (
      <span className="var-chip var-none">
        {suppressed && n === 0 ? "no closed episodes" : "—"}
      </span>
    );
  }
  const over = value > 0;
  if (suppressed) {
    return (
      <span
        className="var-chip var-lown"
        title={`Based on ${n} closed episode${n === 1 ? "" : "s"} — under the ${minN}-episode threshold, so read as indicative only`}
      >
        {fmtSigned(value)} {over ? "over" : "under"}
        <em>n={n}</em>
      </span>
    );
  }
  return (
    <span
      className="var-chip"
      style={{
        color: over ? OVER : UNDER,
        background: over ? "#faecea" : "#e3f4f1",
      }}
    >
      {fmtSigned(value)} {over ? "over" : "under"}
    </span>
  );
}

function KpiTile({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "over" | "under";
}) {
  return (
    <div className="kpi-tile">
      <span className="kpi-label">{label}</span>
      <span
        className="kpi-value"
        style={tone ? { color: tone === "over" ? OVER : UNDER } : undefined}
      >
        {value}
      </span>
      {sub && <span className="kpi-sub">{sub}</span>}
    </div>
  );
}

// ---------------------------------------------------------------------------

function FacilityTable({
  facilities,
  minN,
  selectedKey,
  onSelect,
}: {
  facilities: FacilityRow[];
  minN: number;
  selectedKey: string | null;
  onSelect: (key: string) => void;
}) {
  const maxSpend = Math.max(...facilities.map((f) => f.total_spend), 1);
  const maxPerDay = Math.max(
    ...facilities.map((f) => f.cost_per_post_acute_day ?? 0),
    1,
  );

  return (
    <div className="roster-scroll">
      <table className="roster exec-table">
        <thead>
          <tr>
            <th>Destination</th>
            <th>Episodes</th>
            <th>Total paid</th>
            <th>Cost / post-acute day</th>
            <th>Avg IP LOS</th>
            <th>Readmit</th>
            <th>Avg vs TEAM target</th>
          </tr>
        </thead>
        <tbody>
          {facilities.map((f) => (
            <tr
              key={f.facility_key}
              className={[
                f.facility_key === selectedKey ? "selected" : "",
                f.is_price_outlier ? "row-flagged" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              tabIndex={0}
              onClick={() => onSelect(f.facility_key)}
              onKeyDown={(ev) => {
                if (ev.key === "Enter" || ev.key === " ") {
                  ev.preventDefault();
                  onSelect(f.facility_key);
                }
              }}
            >
              <td>
                <span className="patient-name">{f.facility_name}</span>
                <span className="patient-sub">
                  {f.setting_label}
                  {f.ownership !== "none" && ` · ${f.ownership.replace("_", "-")}`}
                </span>
                {f.is_price_outlier && (
                  <span className="flag-tag">
                    ⚑ {f.price_ratio?.toFixed(1)}× freestanding peer rate
                  </span>
                )}
              </td>
              <td className="days">
                {f.episodes}
                <span className="patient-sub">{f.closed_episodes} closed</span>
              </td>
              <td>
                <CellBar
                  value={f.total_spend}
                  max={maxSpend}
                  label={fmtMoney(f.total_spend)}
                  title={fmtMoneyFull(f.total_spend)}
                />
              </td>
              <td>
                {f.cost_per_post_acute_day ? (
                  <CellBar
                    value={f.cost_per_post_acute_day}
                    max={maxPerDay}
                    label={fmtMoneyFull(f.cost_per_post_acute_day)}
                    title={
                      f.peer_cost_per_day
                        ? `Freestanding peer median ${fmtMoneyFull(
                            f.peer_cost_per_day,
                          )}/day`
                        : undefined
                    }
                  />
                ) : (
                  <span className="eng-none">—</span>
                )}
              </td>
              <td className="days">{f.avg_ip_los ?? "—"}</td>
              <td className="days">{fmtPct(f.readmit_rate)}</td>
              <td>
                <VarianceChip
                  value={f.avg_variance}
                  suppressed={f.delta_suppressed}
                  minN={minN}
                  n={f.closed_episodes}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------

/**
 * How one episode's overage decomposes.
 *
 * Bar *length* is the episode's variance over target, scaled to the worst row
 * in the table; the segments within it are the composition. Two earlier cuts
 * were worse: scaling each bar to its own 100% gave every row a full-width bar,
 * and scaling by summed category excess clustered them all near the maximum,
 * because an episode can be excess-heavy in several categories without being
 * far over target. Length now encodes the column the table is sorted by, and
 * the segments answer "why".
 */
function DriverBar({
  episode,
  maxVariance,
}: {
  episode: EpisodeCostRow;
  maxVariance: number;
}) {
  if (!episode.drivers.length) {
    return (
      <span className="patient-sub">
        {episode.actual_spend === 0
          ? "No claims in the window yet"
          : "At or below peer median in every category"}
      </span>
    );
  }
  const variance = episode.variance ?? 0;
  const width =
    maxVariance > 0 && variance > 0
      ? Math.max(6, (variance / maxVariance) * 100)
      : 100;

  return (
    <div className="driver-wrap">
      <div className="driver-bar" style={{ width: `${width}%` }}>
        {episode.drivers.map((d, i) => (
          <div
            key={d.category}
            className="driver-seg"
            style={{
              width: `${d.share}%`,
              background: DRIVER_RAMP[Math.min(i, DRIVER_RAMP.length - 1)],
            }}
            title={`${d.label}: ${fmtMoneyFull(d.excess)} over peer median (${d.share}%)`}
          />
        ))}
      </div>
      <div className="driver-legend">
        {episode.drivers.slice(0, 3).map((d, i) => (
          <span key={d.category}>
            <i
              style={{ background: DRIVER_RAMP[Math.min(i, DRIVER_RAMP.length - 1)] }}
            />
            {d.label} <strong>{d.share}%</strong>
          </span>
        ))}
      </div>
    </div>
  );
}

function EpisodeTable({
  episodes,
  onOpenPatient,
}: {
  episodes: EpisodeCostRow[];
  onOpenPatient: (fin: string) => void;
}) {
  const maxVariance = Math.max(...episodes.map((e) => e.variance ?? 0), 1);
  return (
    <div className="roster-scroll">
      <table className="roster exec-table">
        <thead>
          <tr>
            <th>Patient</th>
            <th>Status</th>
            <th>Paid</th>
            <th>TEAM target</th>
            <th>Variance</th>
            <th>What is driving the excess</th>
          </tr>
        </thead>
        <tbody>
          {episodes.map((e) => (
            <tr
              key={e.fin}
              className={e.is_outlier ? "row-flagged" : undefined}
              tabIndex={0}
              onClick={() => onOpenPatient(e.fin)}
              onKeyDown={(ev) => {
                if (ev.key === "Enter" || ev.key === " ") {
                  ev.preventDefault();
                  onOpenPatient(e.fin);
                }
              }}
              title="Open this patient in the care-team view"
            >
              <td>
                <span className="patient-name">{e.patient_name}</span>
                <span className="patient-sub">
                  {e.age != null && `${e.age}y · `}DRG {e.ms_drg} · MRN {e.mrn}
                </span>
                {e.had_readmission && <span className="flag-tag">⚑ readmitted</span>}
              </td>
              <td>
                <span className={`status status-${e.status === "closed" ? "completed" : "active"}`}>
                  {e.status === "closed"
                    ? "closed"
                    : e.status === "predischarge"
                      ? "inpatient"
                      : "in flight"}
                </span>
                {e.status !== "closed" && e.target_consumed_pct != null && (
                  <span className="patient-sub">
                    {fmtPct(e.target_consumed_pct)} of target spent
                  </span>
                )}
              </td>
              <td className="days">{fmtMoneyFull(e.actual_spend)}</td>
              <td className="days">{fmtMoneyFull(e.target_price)}</td>
              <td>
                <VarianceChip value={e.variance} />
                {e.variance == null && e.status !== "closed" && (
                  <span className="patient-sub">window still open</span>
                )}
              </td>
              <td>
                <DriverBar episode={e} maxVariance={maxVariance} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------

/**
 * Grouped horizontal bars: one destination against the cohort, by category.
 *
 * Rows sort by the larger of the two values so the categories that carry the
 * argument sit at the top and the near-zero tail falls away. A zero renders as
 * a dash, not a 1px stub with "$0" beside it — a bar that short reads as a
 * rendering fault rather than as an absence.
 */
function CostCategoryChart({ data }: { data: CostCategoryResponse }) {
  const rows = [...data.categories].sort(
    (a, b) =>
      Math.max(b.selected_per_episode, b.cohort_per_episode) -
      Math.max(a.selected_per_episode, a.cohort_per_episode),
  );
  const max = Math.max(
    ...rows.flatMap((c) => [c.selected_per_episode, c.cohort_per_episode]),
    1,
  );

  const bar = (value: number, color: string, title: string) => (
    <div className="cat-bar-line">
      {value > 0 ? (
        <div
          className="cat-bar"
          style={{ width: `${Math.max(0.6, (value / max) * 100)}%`, background: color }}
          title={title}
        />
      ) : null}
      <span className={value > 0 ? "cat-val" : "cat-val cat-val-zero"}>
        {value > 0 ? fmtMoney(value) : "none"}
      </span>
    </div>
  );

  return (
    <div className="cat-chart">
      <div className="chart-legend">
        <span>
          <i style={{ background: SERIES_SELECTED }} /> {data.selected_label}
        </span>
        <span>
          <i style={{ background: SERIES_COHORT }} /> Cohort average
        </span>
      </div>
      {rows.map((c) => {
        const ratio =
          c.cohort_per_episode > 0 && c.selected_per_episode > 0
            ? c.selected_per_episode / c.cohort_per_episode
            : null;
        const notable = ratio != null && (ratio >= 1.5 || ratio <= 0.67);
        return (
          <div className={`cat-row${notable ? " cat-notable" : ""}`} key={c.category}>
            <span className="cat-label">{c.label}</span>
            <div className="cat-bars">
              {bar(
                c.selected_per_episode,
                SERIES_SELECTED,
                `${data.selected_label}: ${fmtMoneyFull(c.selected_per_episode)} per episode`,
              )}
              {bar(
                c.cohort_per_episode,
                SERIES_COHORT,
                `Cohort average: ${fmtMoneyFull(c.cohort_per_episode)} per episode`,
              )}
            </div>
            <span
              className="cat-ratio"
              style={
                ratio == null
                  ? undefined
                  : { color: ratio >= 1.5 ? OVER : ratio <= 0.67 ? UNDER : "var(--muted)" }
              }
            >
              {ratio == null ? "" : `${ratio.toFixed(1)}×`}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/**
 * Closing recommendation. The two-bar price comparison is lifted straight from
 * the reference deck's most persuasive panel — the single thing on that slide
 * that is a decision rather than a statistic, so it earns the last word here.
 */
function OpportunityCard({
  opp,
  onSelectFacility,
}: {
  opp: NonNullable<ExecSummaryResponse["opportunity"]>;
  onSelectFacility: (key: string) => void;
}) {
  const max = Math.max(opp.cost_per_day, opp.peer_cost_per_day, 1);
  return (
    <section className="panel opportunity">
      <div className="panel-h">
        <h2>
          <span className="sec-num">05</span> Where to act
        </h2>
        <span className="dtag">price, not acuity</span>
      </div>
      <div className="opp-body">
        <div className="opp-left">
          <p className="opp-headline">{opp.headline}</p>
          <div className="opp-compare">
            <div className="opp-cmp-row">
              <span className="opp-cmp-label">{opp.facility_name}</span>
              <div className="opp-cmp-track">
                <div
                  className="opp-cmp-bar"
                  style={{
                    width: `${(opp.cost_per_day / max) * 100}%`,
                    background: OVER,
                  }}
                />
              </div>
              <span className="opp-cmp-val" style={{ color: OVER }}>
                {fmtMoneyFull(opp.cost_per_day)}
                <small>/day</small>
              </span>
            </div>
            <div className="opp-cmp-row">
              <span className="opp-cmp-label">Freestanding peer median</span>
              <div className="opp-cmp-track">
                <div
                  className="opp-cmp-bar"
                  style={{
                    width: `${(opp.peer_cost_per_day / max) * 100}%`,
                    background: UNDER,
                  }}
                />
              </div>
              <span className="opp-cmp-val" style={{ color: UNDER }}>
                {fmtMoneyFull(opp.peer_cost_per_day)}
                <small>/day</small>
              </span>
            </div>
            <div className="opp-cmp-gap">
              <span>
                {opp.price_ratio.toFixed(1)}× the peer rate for comparable days
              </span>
            </div>
          </div>
          <p className="opp-action">{opp.action}</p>
        </div>
        <div className="opp-right">
          <span className="kpi-label">Avoidable spend</span>
          <span className="opp-hero">{fmtMoneyFull(opp.avoidable_spend)}</span>
          <span className="kpi-sub">
            {fmtMoneyFull(opp.avoidable_per_episode)} per episode
          </span>
          <span className="kpi-sub">
            {opp.episodes} episodes · {opp.post_acute_days} post-acute days
          </span>
          <button
            type="button"
            className="opp-btn"
            onClick={() => onSelectFacility(opp.facility_key)}
          >
            See the {opp.episodes} episodes →
          </button>
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------

export default function ExecView({
  facilityKey,
  onMeta,
  onSelectFacility,
  onOpenPatient,
}: {
  facilityKey: string | null;
  onMeta: (meta: ViewMeta) => void;
  onSelectFacility: (key: string | null) => void;
  onOpenPatient: (fin: string) => void;
}) {
  const [summary, setSummary] = useState<ExecSummaryResponse | null>(null);
  const [facilities, setFacilities] = useState<FacilityRow[] | null>(null);
  const [drill, setDrill] = useState<FacilityDetailResponse | null>(null);
  const [outliers, setOutliers] = useState<OutlierResponse | null>(null);
  const [categories, setCategories] = useState<CostCategoryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchExecSummary(), fetchFacilities(), fetchOutliers(8)])
      .then(([s, f, o]) => {
        setSummary(s);
        setFacilities(f.facilities);
        setOutliers(o);
        onMeta({
          as_of: s.meta.as_of,
          as_of_mode: s.meta.as_of_mode,
          org_name: s.meta.org_name,
          summary: `${s.meta.episodes} episodes · ${s.meta.closed_episodes} closed · ${s.meta.in_flight_episodes} in flight`,
        });
      })
      .catch((err) => setError(String(err)));
  }, [onMeta]);

  // The category panel follows the drill selection; with nothing selected the
  // API picks the flagged outlier, so the panel opens on something worth seeing.
  useEffect(() => {
    let cancelled = false;
    fetchCostCategories(facilityKey ?? undefined)
      .then((c) => !cancelled && setCategories(c))
      .catch(() => !cancelled && setCategories(null));
    return () => {
      cancelled = true;
    };
  }, [facilityKey]);

  useEffect(() => {
    if (!facilityKey) {
      setDrill(null);
      return;
    }
    let cancelled = false;
    fetchFacilityEpisodes(facilityKey)
      .then((d) => !cancelled && setDrill(d))
      .catch((err) => !cancelled && setError(String(err)));
    return () => {
      cancelled = true;
    };
  }, [facilityKey]);

  if (error) return <div className="error">Failed to load executive view: {error}</div>;
  if (!summary || !facilities) return <div className="panel">Loading…</div>;

  const k = summary.kpis;
  const opp = summary.opportunity;

  return (
    <div className="exec-stack">
      {/* 01 — the size and shape of the book of business */}
      <section className="panel">
        <div className="panel-h">
          <h2>
            <span className="sec-num">01</span> 30-day episode economics
          </h2>
          <span className="dtag">D13 · D15 · Medicare paid vs TEAM target price</span>
        </div>

        <div className="kpi-hero">
          <div className="kpi-hero-fig">
            <span className="kpi-label">Episode spend to date</span>
            <span className="kpi-hero-value">{fmtMoney(k.total_spend)}</span>
            <span className="kpi-sub">
              {k.episodes} episodes · {fmtPct(k.post_acute_share)} of it post-acute
            </span>
          </div>
          <div className="kpi-hero-fig">
            <span className="kpi-label">Net vs TEAM target</span>
            <span
              className="kpi-hero-value"
              style={{ color: (k.net_savings_closed ?? 0) < 0 ? OVER : UNDER }}
            >
              {fmtSigned(k.net_savings_closed)}
            </span>
            <span className="kpi-sub">
              across {k.closed_episodes} closed episodes ·{" "}
              {k.episodes_over_target} over target
            </span>
          </div>
        </div>

        <div className="kpi-row">
          <KpiTile
            label="Avg spend / closed episode"
            value={fmtMoney(k.avg_spend_closed)}
            sub={`vs ${fmtMoney(k.avg_target_closed)} target`}
          />
          <KpiTile
            label="30-day readmission"
            value={fmtPct(k.readmit_rate_closed, 1)}
            sub={`${k.closed_episodes} closed episodes`}
          />
          <KpiTile
            label="Discharged home"
            value={fmtPct(k.pct_discharged_home, 0)}
            sub="home or home health"
          />
          <KpiTile
            label="Avg inpatient LOS"
            value={`${k.avg_ip_los ?? "—"} d`}
            sub="anchor stay"
          />
        </div>

        <p className="data-note">
          {summary.meta.claims_lag_note} Savings and readmission rates cover the{" "}
          {summary.meta.closed_episodes} episodes whose 30-day window has closed;{" "}
          {summary.meta.in_flight_episodes} are still in flight and report
          spend-to-date only.
        </p>
      </section>

      {/* 02 — where the money goes, and the drill-down it opens */}
      <section className="panel">
        <div className="panel-h">
          <h2>
            <span className="sec-num">02</span> Cost and outcomes by discharge
            destination
          </h2>
          <span className="dtag">click a row to drill into its patients</span>
        </div>
        <FacilityTable
          facilities={facilities}
          minN={summary.meta.min_n_for_delta}
          selectedKey={facilityKey}
          onSelect={(key) => onSelectFacility(key === facilityKey ? null : key)}
        />
      </section>

      {drill && (
        <section className="panel panel-drill">
          <div className="panel-h">
            <h2>
              <span className="sec-eyebrow">Drill-down</span>{" "}
              {drill.facility.facility_name}
            </h2>
            <button
              type="button"
              className="link-btn"
              onClick={() => onSelectFacility(null)}
            >
              ← All destinations
            </button>
          </div>
          <p className="data-note">
            {drill.facility.episodes} episodes ·{" "}
            {fmtMoneyFull(drill.facility.total_spend)} total paid ·{" "}
            {drill.facility.post_acute_days} post-acute days at{" "}
            {fmtMoneyFull(drill.facility.cost_per_post_acute_day)}/day. Click any
            patient to open their episode in the care-team view.
          </p>
          <EpisodeTable episodes={drill.episodes} onOpenPatient={onOpenPatient} />
        </section>
      )}

      {/* 03 — which category is actually out of line */}
      {categories && (
        <section className="panel">
          <div className="panel-h">
            <h2>
              <span className="sec-num">03</span> Spend per episode by cost category
            </h2>
            <span className="dtag">
              benchmark is this cohort&rsquo;s own average, not an external region
            </span>
          </div>
          <CostCategoryChart data={categories} />
          <p className="data-note">
            This is how an acuity objection gets settled: if a destination&rsquo;s
            anchor inpatient spend sits at or below the cohort while one
            post-acute line runs multiples above it, the gap is price, not case
            mix.
          </p>
        </section>
      )}

      {/* 04 — the individual patients behind the overage */}
      {outliers && outliers.episodes.length > 0 && (
        <section className="panel">
          <div className="panel-h">
            <h2>
              <span className="sec-num">04</span> Outlier episodes
            </h2>
            <span className="dtag">furthest over TEAM target · closed episodes</span>
          </div>
          <EpisodeTable episodes={outliers.episodes} onOpenPatient={onOpenPatient} />
        </section>
      )}

      {/* 05 — the conclusion: one named, quantified thing to do */}
      {opp && <OpportunityCard opp={opp} onSelectFacility={onSelectFacility} />}
    </div>
  );
}
