/**
 * Dashboard shell — header, view switcher, and one of two surfaces.
 *
 * The dashboard now serves two audiences with the same data. The executive view
 * (D13/D15) answers "where is the money going" for a CFO or VP of care
 * transitions and is the landing view; the care-team view is the original
 * roster / triage / episode surface, unchanged, for the people working patients.
 *
 * The two are linked in both directions: an exec drilling into an expensive
 * facility can click a patient and land on that patient's episode here, and the
 * care-team roster is where they end up. Dollars → cause → intervention.
 */
import { useCallback, useState } from "react";
import CareTeamView from "./CareTeamView";
import ExecView from "./ExecView";
import { ViewId, ViewMeta, useNavState } from "./viewState";

const VIEWS: { id: ViewId; label: string; hint: string }[] = [
  { id: "exec", label: "Executive", hint: "Cost and outcomes by care setting" },
  { id: "care", label: "Care team", hint: "Roster, triage queue, episode detail" },
];

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return `${m}/${d}/${y}`;
}

export default function App() {
  const [nav, navigate] = useNavState();
  const [meta, setMeta] = useState<ViewMeta | null>(null);

  // Each view owns its own data fetch and lifts the header line up, so the
  // shell never issues a duplicate request just to fill in the as-of date.
  const onMeta = useCallback((next: ViewMeta) => setMeta(next), []);

  return (
    <div className="wrap">
      <header>
        <div className="brand">
          <h1>SHFFT Episode Command</h1>
          <p>{meta?.org_name ?? "…"}</p>
        </div>
        <div className="header-meta">
          {meta ? (
            <>
              <div>
                As-of <strong>{fmtDate(meta.as_of)}</strong>{" "}
                <span className={`mode mode-${meta.as_of_mode}`}>
                  {meta.as_of_mode === "frozen" ? "frozen demo" : "live today()"}
                </span>
              </div>
              <div className="counts">{meta.summary}</div>
            </>
          ) : (
            <div>Loading…</div>
          )}
          <span className="synthetic-tag">Synthetic data</span>
        </div>
      </header>

      <nav className="view-switch" aria-label="Dashboard view">
        {VIEWS.map((v) => (
          <button
            key={v.id}
            type="button"
            className={nav.view === v.id ? "active" : undefined}
            aria-current={nav.view === v.id ? "page" : undefined}
            title={v.hint}
            onClick={() => navigate({ view: v.id })}
          >
            {v.label}
          </button>
        ))}
      </nav>

      {nav.view === "exec" ? (
        <ExecView
          facilityKey={nav.facility}
          onMeta={onMeta}
          onSelectFacility={(facility) => navigate({ facility })}
          onOpenPatient={(fin) => navigate({ view: "care", fin })}
        />
      ) : (
        <CareTeamView initialFin={nav.fin} onMeta={onMeta} />
      )}
    </div>
  );
}
