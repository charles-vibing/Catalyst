/**
 * Appointments (A7 / A11).
 *
 * Two actions per appointment: confirm you'll attend, and afterwards answer
 * "did you go?". The second one matters beyond the patient's own record — for a
 * primary care visit it writes referral_status_event, which is what the
 * dashboard's TEAM PCP tracker reads for completed / no-show. That saves a
 * navigator a phone call per patient.
 */

import { useEffect, useState } from "react";
import {
  Appointment,
  AppointmentListResponse,
  confirmAppointment,
  fetchAppointments,
  recordAttendance,
} from "./api";
import { Card, ErrorNote, Loading, friendlyDate, timeOf } from "./components/ui";

const KIND_GLYPHS: Record<string, string> = {
  surgeon: "🩺",
  pcp: "🏥",
  pt: "🏃",
  home_health: "🏡",
};

function AppointmentRow({
  a,
  onChanged,
}: {
  a: Appointment;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);

  async function confirm() {
    setBusy(true);
    try {
      await confirmAppointment(a.id);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function attended(went: boolean) {
    setBusy(true);
    try {
      await recordAttendance(a.id, went);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="row">
      <div className="grow">
        <div className="name">
          <span aria-hidden="true" style={{ marginRight: 7 }}>
            {KIND_GLYPHS[a.kind] ?? "•"}
          </span>
          {a.title}
        </div>
        <div className="meta">
          {friendlyDate(a.scheduled_at)}
          {timeOf(a.scheduled_at) ? ` at ${timeOf(a.scheduled_at)}` : ""}
        </div>
        {a.provider_name && <div className="meta">{a.provider_name}</div>}
        {a.location && <div className="meta">{a.location}</div>}

        <div className="btn-row" style={{ marginTop: 10 }}>
          {a.due_soon && !a.confirmed && <span className="chip due">Coming up</span>}
          {a.confirmed && !a.is_past && <span className="chip ok">You're going</span>}
          {a.attended === true && <span className="chip ok">✓ You went</span>}
          {a.attended === false && <span className="chip anticoagulant">Missed</span>}

          {!a.is_past && !a.confirmed && (
            <button type="button" className="btn primary" disabled={busy} onClick={confirm}>
              I'll be there
            </button>
          )}
          {a.is_past && a.attended === null && (
            <>
              <button
                type="button"
                className="btn primary"
                disabled={busy}
                onClick={() => attended(true)}
              >
                I went
              </button>
              <button
                type="button"
                className="btn"
                disabled={busy}
                onClick={() => attended(false)}
              >
                I didn't go
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function Appointments({ onChanged }: { onChanged: () => void }) {
  const [data, setData] = useState<AppointmentListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    fetchAppointments()
      .then(setData)
      .catch((e) => setError(String(e.message ?? e)));
  }

  useEffect(load, []);

  if (error && !data) return <div className="screen"><ErrorNote error={error} /></div>;
  if (!data) return <Loading what="your appointments" />;

  function refresh() {
    onChanged();
    load();
  }

  return (
    <div className="screen">
      <h2>Appointments</h2>
      <p className="lede">Confirm the ones coming up, and tell us how the past ones went.</p>

      {data.needs_attendance_answer.length > 0 && (
        <Card title="Did you make it to these?" tinted>
          {data.needs_attendance_answer.map((a) => (
            <AppointmentRow key={a.id} a={a} onChanged={refresh} />
          ))}
        </Card>
      )}

      <Card title="Coming up">
        {data.upcoming.length === 0 && <div className="sub">Nothing scheduled right now.</div>}
        {data.upcoming.map((a) => (
          <AppointmentRow key={a.id} a={a} onChanged={refresh} />
        ))}
      </Card>

      {data.past.length > 0 && (
        <Card title="Past appointments">
          {data.past
            .filter((a) => a.attended !== null)
            .map((a) => (
              <AppointmentRow key={a.id} a={a} onChanged={refresh} />
            ))}
        </Card>
      )}

      <div className="sub" style={{ textAlign: "center", fontSize: 13 }}>
        Reminders show in the app only — this prototype doesn't text or call you.
      </div>
    </div>
  );
}
