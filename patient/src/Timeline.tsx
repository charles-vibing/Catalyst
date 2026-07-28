/**
 * Recovery timeline (A2) — the app's home screen.
 *
 * Milestone-based and framed as "you're on track for X". There is deliberately
 * NO day counter anywhere on this screen: the 30-day episode is a payment
 * window, and counting it down at a recovering patient is both unhelpful and
 * faintly threatening. The API returns days_remaining in `meta` for the
 * provider surface; this screen ignores it.
 */

import { Milestone, TimelineResponse } from "./api";
import { Card, Stat, friendlyDate } from "./components/ui";

function MilestoneRow({ m }: { m: Milestone }) {
  const mark = m.status === "met" ? "✓" : m.status === "missed" ? "!" : "";
  return (
    <div className={`milestone ${m.status}`}>
      <div className="mark" aria-hidden="true">
        {mark}
      </div>
      <div className="grow">
        <div className="m-label">{m.label}</div>
        <div className="m-meta">
          {m.status === "met"
            ? "Done"
            : m.status === "missed"
              ? "Let's catch up on this — your care team can help"
              : m.target_date
                ? `Aiming for ${friendlyDate(m.target_date)}`
                : ""}
        </div>
      </div>
    </div>
  );
}

export default function Timeline({
  data,
  onGoTo,
}: {
  data: TimelineResponse;
  onGoTo: (tab: string) => void;
}) {
  const p = data.progress;
  const current = data.milestones.filter((m) => m.phase === data.phase);
  const others = data.milestones.filter((m) => m.phase !== data.phase);

  return (
    <div className="screen">
      <div className="hero">
        <div className="phase">{data.phase_label}</div>
        <h2>{data.headline}</h2>
        <p>{data.subhead}</p>
      </div>

      <div className="phase-track">
        {data.phases.map((ph) => (
          <div key={ph.phase} className={`phase-step ${ph.state}`}>
            <div className="bar" />
            <div className="name">{ph.label}</div>
          </div>
        ))}
      </div>

      <div className="stats">
        <Stat value={`${p.checkin.pct ?? 0}%`} label="Check-ins" />
        <Stat value={`${p.pt.pct ?? 0}%`} label="Exercises" />
        <Stat value={`${p.medication.pct ?? 0}%`} label="Medicines" />
      </div>

      <Card title="Where you are now">
        {current.length === 0 && <div className="sub">No goals in this stage.</div>}
        {current.map((m) => (
          <MilestoneRow key={m.code} m={m} />
        ))}
      </Card>

      {others.length > 0 && (
        <Card title="The rest of your plan">
          {others.map((m) => (
            <MilestoneRow key={m.code} m={m} />
          ))}
        </Card>
      )}

      <div className="btn-row">
        <button
          type="button"
          className="btn primary"
          style={{ flex: 1 }}
          onClick={() => onGoTo("checkin")}
        >
          Today's check-in
        </button>
        <button type="button" className="btn danger" onClick={() => onGoTo("symptoms")}>
          Something's wrong
        </button>
      </div>
    </div>
  );
}
