import {
  CareTeamMember,
  ClinicalDocument,
  DischargeMed,
  DischargeVitals,
  EpisodeDetailResponse,
  LabResult,
  Problem,
  TimelineEvent,
} from "./api";

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const day = iso.slice(0, 10);
  const [y, m, d] = day.split("-");
  if (!y || !m || !d) return iso;
  return `${m}/${d}/${y}`;
}

function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const day = fmtDate(iso);
  const time = iso.includes("T") ? iso.slice(11, 16) : "";
  return time ? `${day} ${time}` : day;
}

function docLabel(t: string): string {
  const map: Record<string, string> = {
    discharge: "Discharge summary",
    hp: "H&P",
    op: "Operative note",
    anesthesia: "Anesthesia",
    rad: "Radiology",
  };
  return map[t] ?? t;
}

function labFlagClass(flag: string | null): string {
  if (!flag) return "chip";
  const f = flag.toUpperCase();
  if (f === "H" || f === "L" || f === "HH" || f === "LL" || f === "A") {
    return "chip chip-warn";
  }
  return "chip";
}

function VitalsBlock({ v }: { v: DischargeVitals }) {
  const bp =
    v.bp_systolic != null && v.bp_diastolic != null
      ? `${v.bp_systolic}/${v.bp_diastolic}`
      : null;
  const items: { k: string; val: string }[] = [];
  if (bp) items.push({ k: "BP", val: bp });
  if (v.heart_rate != null) items.push({ k: "HR", val: String(v.heart_rate) });
  if (v.temp_f != null) items.push({ k: "Temp", val: `${v.temp_f}°F` });
  if (v.spo2_percent != null) {
    items.push({
      k: "SpO₂",
      val: `${v.spo2_percent}%${v.o2_delivery ? ` · ${v.o2_delivery}` : ""}`,
    });
  }
  if (v.resp_rate != null) items.push({ k: "RR", val: String(v.resp_rate) });
  if (v.pain_score != null) items.push({ k: "Pain", val: String(v.pain_score) });

  return (
    <div>
      <div className="muted-line">As of {fmtDateTime(v.recorded_at)}</div>
      <div className="stat-row">
        {items.map((i) => (
          <div className="stat" key={i.k}>
            <span>{i.k}</span>
            <strong>{i.val}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

function MedList({ meds }: { meds: DischargeMed[] }) {
  if (meds.length === 0) return <p className="empty-block">No discharge meds on file.</p>;
  return (
    <ul className="med-list">
      {meds.map((m) => (
        <li key={m.name + (m.sig ?? "")}>
          <strong>{m.name}</strong>
          {m.sig && <span className="med-sig">{m.sig}</span>}
        </li>
      ))}
    </ul>
  );
}

function LabChips({ labs }: { labs: LabResult[] }) {
  if (labs.length === 0) return <p className="empty-block">No key labs near discharge.</p>;
  return (
    <div className="chips">
      {labs.map((l) => (
        <span key={l.display} className={labFlagClass(l.abnormal_flag)} title={l.effective_at ?? undefined}>
          {l.display} {l.value ?? "—"}
          {l.unit ? ` ${l.unit}` : ""}
          {l.abnormal_flag ? ` (${l.abnormal_flag})` : ""}
        </span>
      ))}
    </div>
  );
}

function ProblemChips({ problems }: { problems: Problem[] }) {
  if (problems.length === 0) return <p className="empty-block">No active problems.</p>;
  return (
    <div className="chips">
      {problems.map((p) => (
        <span key={p.description} className="chip" title={p.icd10 ?? undefined}>
          {p.description}
        </span>
      ))}
    </div>
  );
}

function Timeline({ events }: { events: TimelineEvent[] }) {
  if (events.length === 0) return <p className="empty-block">No timeline events.</p>;
  return (
    <ol className="timeline">
      {events.map((ev, i) => (
        <li key={`${ev.kind}-${ev.at}-${i}`} className={`tl-${ev.kind}`}>
          <div className="tl-when">{fmtDateTime(ev.at)}</div>
          <div className="tl-label">{ev.label}</div>
          {ev.detail && <div className="tl-detail">{ev.detail}</div>}
        </li>
      ))}
    </ol>
  );
}

function CareTeam({ team }: { team: CareTeamMember[] }) {
  if (team.length === 0) return <p className="empty-block">No care team listed.</p>;
  return (
    <ul className="care-list">
      {team.map((m) => (
        <li key={m.role + m.name}>
          <span className="care-role">{m.role}</span>
          <span>{m.name}</span>
        </li>
      ))}
    </ul>
  );
}

function DocList({ fin, docs }: { fin: string; docs: ClinicalDocument[] }) {
  if (docs.length === 0) return <p className="empty-block">No documents indexed.</p>;
  return (
    <ul className="doc-list">
      {docs.map((d) => {
        const href =
          d.file_name != null
            ? `/api/episodes/${encodeURIComponent(fin)}/documents/${encodeURIComponent(d.file_name)}`
            : null;
        const label = docLabel(d.document_type);
        return (
          <li key={d.file_name ?? d.document_type}>
            {href ? (
              <a className="doc-link" href={href} target="_blank" rel="noopener noreferrer">
                {label}
              </a>
            ) : (
              <span className="doc-type">{label}</span>
            )}
            {d.service_date && <span className="muted-line">{fmtDate(d.service_date)}</span>}
          </li>
        );
      })}
    </ul>
  );
}

type Props = {
  detail: EpisodeDetailResponse | null;
  loading: boolean;
  error: string | null;
};

export default function EpisodeDetail({ detail, loading, error }: Props) {
  if (loading) {
    return <div className="detail-empty">Loading episode…</div>;
  }
  if (error) {
    return <div className="detail-empty error-inline">Failed to load episode: {error}</div>;
  }
  if (!detail) {
    return <div className="detail-empty">Select an episode from the roster.</div>;
  }

  const e = detail.episode;
  const demo = [e.age != null ? `${e.age}${e.sex ?? ""}` : null, e.procedure_summary]
    .filter(Boolean)
    .join(" · ");
  const disp = detail.disposition_context;
  const therapy = detail.therapy;
  const pcp = detail.pcp;

  return (
    <div className="detail-body">
      <div className="col">
        <div className="patient-head">
          <h3>{e.patient_name}</h3>
          <div className="sub">
            MRN {e.mrn} · FIN {e.fin}
            {e.attending_name ? ` · ${e.attending_name}` : ""}
          </div>
          {demo && <div className="sub">{demo}</div>}
          <div className="stat-row">
            <div className="stat">
              <span>Admit</span>
              <strong>{fmtDate(e.admit_date)}</strong>
            </div>
            <div className="stat">
              <span>Discharge</span>
              <strong>{fmtDate(e.discharge_date)}</strong>
            </div>
            <div className="stat">
              <span>LOS</span>
              <strong>{e.length_of_stay_days ?? "—"}</strong>
            </div>
            <div className="stat">
              <span>MS-DRG</span>
              <strong>{e.ms_drg ?? "—"}</strong>
            </div>
            <div className="stat">
              <span>Days left</span>
              <strong>{e.days_remaining ?? "—"}</strong>
            </div>
            <div className="stat">
              <span>Status</span>
              <strong className={`status status-${e.status}`}>{e.status}</strong>
            </div>
          </div>
        </div>

        <div className="lbl">Index stay</div>
        {e.principal_diagnosis && (
          <p className="body-line">
            <strong>Dx:</strong> {e.principal_diagnosis}
          </p>
        )}
        {e.procedure_summary && (
          <p className="body-line">
            <strong>Procedure:</strong> {e.procedure_summary}
            {e.procedure_date ? ` (${fmtDate(e.procedure_date)})` : ""}
          </p>
        )}
        {therapy?.weight_bearing && (
          <p className="body-line">
            <strong>Weight-bearing:</strong> {therapy.weight_bearing}
          </p>
        )}
        {therapy && therapy.equipment.length > 0 && (
          <p className="body-line">
            <strong>DME:</strong> {therapy.equipment.join(", ")}
          </p>
        )}

        <div className="lbl">Comorbidities</div>
        <ProblemChips problems={detail.problems} />

        <div className="lbl">Key labs near discharge</div>
        <LabChips labs={detail.labs} />

        <div className="lbl">Discharge vitals</div>
        {detail.discharge_vitals ? (
          <VitalsBlock v={detail.discharge_vitals} />
        ) : (
          <p className="empty-block">No vitals on file.</p>
        )}

        <div className="lbl">Discharge medications</div>
        <MedList meds={detail.discharge_meds} />
      </div>

      <div className="col">
        <div className="lbl">Disposition context</div>
        <div className="setting-card">
          <strong>{disp.title}</strong>
          <div className="muted-line">
            {disp.label ?? "Unknown"}
            {disp.code ? ` · CMS ${disp.code}` : ""}
          </div>
          <ul>
            {disp.bullets.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
          {disp.emergency_contact.name && (
            <p className="body-line ec-line">
              Emergency contact: {disp.emergency_contact.name}
              {disp.emergency_contact.relationship
                ? ` (${disp.emergency_contact.relationship})`
                : ""}
              {disp.emergency_contact.phone ? ` · ${disp.emergency_contact.phone}` : ""}
            </p>
          )}
        </div>

        <div className="lbl">PCP referral (TEAM)</div>
        <div className={`pcp-box${pcp?.gap ? " gap" : ""}`}>
          {pcp ? (
            <>
              <strong>{pcp.status ?? "No referral"}</strong>
              {pcp.gap && <span className="gap-tag">Gap</span>}
              {pcp.note && <p className="body-line">{pcp.note}</p>}
              {pcp.appointment_datetime && (
                <p className="muted-line">Appt {fmtDateTime(pcp.appointment_datetime)}</p>
              )}
            </>
          ) : (
            <p className="empty-block">No PCP data.</p>
          )}
        </div>

        <div className="lbl">Care team</div>
        <CareTeam team={detail.care_team} />

        <div className="lbl">Documents</div>
        <DocList fin={e.fin} docs={detail.documents} />
      </div>

      <div className="col">
        <div className="lbl">Clinical timeline</div>
        <Timeline events={detail.timeline} />
      </div>
    </div>
  );
}
