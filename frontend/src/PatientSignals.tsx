/**
 * Patient-app engagement panel for the episode detail view.
 *
 * This is D6 (live signal timeline) from design/core-functionality.md, which the
 * dashboard MVP plan sequenced as M5 but never built — there was no patient app
 * generating signals. Now there is, so this renders what the companion app
 * writes: adherence, the latest check-in, red flags, checklist gaps, and the
 * ordered signal stream.
 *
 * Everything here is read-only. The provider acts on this data through the
 * triage queue (assign / resolve) and the message inbox, not by editing what a
 * patient reported.
 */

import { useEffect, useState } from "react";
import {
  PatientSummaryResponse,
  SignalsResponse,
  fetchPatientSignals,
  fetchPatientSummary,
} from "./api";

const SEVERITY_CLASS: Record<string, string> = {
  red: "sev-red",
  yellow: "sev-yellow",
  green: "sev-green",
};

const MOBILITY_LABELS: Record<string, string> = {
  bed: "in bed",
  chair: "up to chair",
  walker: "walker",
  cane: "cane",
  independent: "independent",
};

function pct(value: number | null): string {
  return value == null ? "—" : `${value}%`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${m}/${d}/${y}`;
}

function fmtStamp(iso: string): string {
  const date = fmtDate(iso);
  const t = iso.slice(11, 16);
  return t ? `${date} ${t}` : date;
}

export default function PatientSignals({ fin }: { fin: string | null }) {
  const [summary, setSummary] = useState<PatientSummaryResponse | null>(null);
  const [signals, setSignals] = useState<SignalsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    if (!fin) {
      setSummary(null);
      setSignals(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([fetchPatientSummary(fin), fetchPatientSignals(fin)])
      .then(([s, sig]) => {
        if (cancelled) return;
        setSummary(s);
        setSignals(sig);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [fin]);

  if (!fin) return null;
  if (loading && !summary) return <div className="ps-empty">Loading patient app data…</div>;
  if (error) return <div className="ps-empty error-inline">{error}</div>;
  if (!summary) return null;

  if (!summary.enrolled) {
    return (
      <div className="ps-empty">
        <strong>Not enrolled in the patient app.</strong>
        <div>
          No check-ins, adherence, or symptom reports for this episode. Engagement
          data appears here once the patient or a caregiver completes onboarding.
        </div>
      </div>
    );
  }

  const a = summary.adherence;
  const latest = summary.latest_checkin;
  const trend = summary.checkin_trend.slice().reverse();
  const visibleSignals = showAll ? signals?.signals ?? [] : (signals?.signals ?? []).slice(0, 12);
  const blockers = summary.checklists.flatMap((c) =>
    c.blockers.map((b) => ({ ...b, title: c.title })),
  );

  return (
    <div className="patient-signals">
      <div className="ps-head">
        <div>
          <span className="ps-phase">{summary.phase_label}</span>
          <span className="ps-by">
            App used by {summary.enrollment?.relationship === "caregiver" ? "caregiver" : "patient"}
            {" · enrolled "}
            {fmtDate(summary.enrollment?.enrolled_at ?? null)}
          </span>
        </div>
        {summary.open_alerts > 0 && (
          <span className="ps-alerts">{summary.open_alerts} open app alert(s)</span>
        )}
      </div>

      <div className="ps-metrics">
        <div className="ps-metric">
          <div className="ps-value">{pct(a.checkin.pct)}</div>
          <div className="ps-label">
            Check-ins
            <span>
              {a.checkin.days_completed}/{a.checkin.days_expected} days
            </span>
          </div>
        </div>
        <div className="ps-metric">
          <div className="ps-value">{pct(a.pt.pct)}</div>
          <div className="ps-label">
            PT adherence
            <span>{a.pt.sessions_logged} sessions</span>
          </div>
        </div>
        <div className="ps-metric">
          <div className="ps-value">{pct(a.medication.pct)}</div>
          <div className="ps-label">
            Medication
            <span>{a.medication.missed} missed</span>
          </div>
        </div>
        <div
          className={
            a.medication.anticoagulant_missed > 0 ? "ps-metric warn" : "ps-metric"
          }
        >
          <div className="ps-value">{pct(a.medication.anticoagulant_pct)}</div>
          <div className="ps-label">
            Anticoagulant
            <span>{a.medication.anticoagulant_missed} missed</span>
          </div>
        </div>
        <div className="ps-metric">
          <div className="ps-value">
            {summary.milestones.filter((m) => m.status === "met").length}/
            {summary.milestones.length}
          </div>
          <div className="ps-label">
            Milestones
            <span>
              {summary.milestones.filter((m) => m.status === "missed").length} missed
            </span>
          </div>
        </div>
      </div>

      <div className="ps-grid">
        <section>
          <h4>Latest check-in</h4>
          {latest ? (
            <div className="ps-latest">
              <div className="ps-latest-date">{fmtDate(latest.checkin_date)}</div>
              <ul>
                <li>
                  Pain <strong>{latest.pain_score ?? "—"}/10</strong>
                </li>
                <li>
                  Mobility{" "}
                  <strong>
                    {MOBILITY_LABELS[latest.mobility_status ?? ""] ??
                      latest.mobility_status ??
                      "—"}
                  </strong>
                </li>
                <li>
                  Weight-bearing{" "}
                  <strong
                    className={
                      latest.weight_bearing_status === "more_than_allowed"
                        ? "ps-flagged"
                        : undefined
                    }
                  >
                    {(latest.weight_bearing_status ?? "—").replace(/_/g, " ")}
                  </strong>
                </li>
                <li>
                  Mood <strong>{latest.mood ?? "—"}</strong>, sleep{" "}
                  <strong>{latest.sleep_quality ?? "—"}</strong>
                </li>
                <li>
                  PT that day <strong>{latest.pt_completed ? "yes" : "no"}</strong>
                </li>
              </ul>
              {trend.length > 1 && (
                <>
                  <div className="ps-trend-label">Pain, oldest → newest</div>
                  <div className="ps-trend">
                    {trend.map((t, i) => (
                      <div
                        key={i}
                        className="ps-bar"
                        style={{ height: `${Math.max(8, ((t.pain_score ?? 0) / 10) * 100)}%` }}
                        title={`${fmtDate(t.checkin_date)}: ${t.pain_score ?? "—"}/10`}
                      />
                    ))}
                  </div>
                </>
              )}
            </div>
          ) : (
            <div className="ps-none">No check-ins yet.</div>
          )}
        </section>

        <section>
          <h4>Symptom reports</h4>
          {summary.red_flags.length === 0 && <div className="ps-none">None reported.</div>}
          {summary.red_flags.map((f) => (
            <div key={f.id} className="ps-flag">
              <span className={`ps-dot ${SEVERITY_CLASS[f.severity] ?? ""}`} />
              <div>
                <div className="ps-flag-cat">
                  {f.category.toUpperCase()} · {fmtDate(f.reported_at)}
                </div>
                <div className="ps-flag-reason">{f.reasons[0] ?? "—"}</div>
                {f.guidance_code && (
                  <div className="ps-flag-guidance">
                    App advised: {f.guidance_code.replace(/_/g, " ")}
                  </div>
                )}
              </div>
            </div>
          ))}

          {blockers.length > 0 && (
            <>
              <h4 className="ps-subhead">Checklist gaps</h4>
              {blockers.map((b) => (
                <div key={b.item_code} className="ps-blocker">
                  <div className="ps-flag-cat">{b.title}</div>
                  <div className="ps-flag-reason">{b.label}</div>
                  {b.note && <div className="ps-flag-guidance">“{b.note}”</div>}
                </div>
              ))}
            </>
          )}
        </section>
      </div>

      <section className="ps-timeline">
        <h4>
          Signal timeline
          <span className="ps-count">{signals?.meta.total ?? 0} events</span>
        </h4>
        {visibleSignals.map((s) => (
          <div key={s.id} className="ps-signal">
            <span className={`ps-dot ${SEVERITY_CLASS[s.severity ?? ""] ?? ""}`} />
            <span className="ps-when">{fmtStamp(s.occurred_at)}</span>
            <span className="ps-kind">{s.label}</span>
            <span className="ps-headline">{s.headline}</span>
          </div>
        ))}
        {(signals?.signals.length ?? 0) > 12 && (
          <button type="button" className="ps-more" onClick={() => setShowAll(!showAll)}>
            {showAll ? "Show fewer" : `Show all ${signals?.signals.length} events`}
          </button>
        )}
      </section>
    </div>
  );
}
