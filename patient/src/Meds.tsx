/**
 * Medication tracker (A4), anticoagulation first.
 *
 * Blood thinners sort to the top and are visually distinguished, because a
 * missed Lovenox/Eliquis/warfarin dose after hip fracture surgery is the one
 * adherence failure with a same-week clot risk. Everything else is secondary.
 *
 * Reminders are in-app only: the due-time chip is the whole reminder mechanism
 * in this MVP. No push, no SMS (see TODO.md).
 */

import { useEffect, useState } from "react";
import { MedListResponse, Medication, fetchMedications, recordDose } from "./api";
import { Card, ErrorNote, Loading, Stat } from "./components/ui";

function MedRow({
  med,
  onRecorded,
}: {
  med: Medication;
  onRecorded: (ack: string, alerted: boolean) => void;
}) {
  const [busy, setBusy] = useState<number | null>(null);

  async function mark(doseIndex: number, status: "taken" | "missed") {
    setBusy(doseIndex);
    try {
      const res = await recordDose({
        med_schedule_id: med.id,
        dose_index: doseIndex,
        status,
      });
      onRecorded(res.acknowledgement, res.alerts.length > 0);
    } finally {
      setBusy(null);
    }
  }

  const isAnticoag = med.med_class === "anticoagulant";

  return (
    <div className="row">
      <div className="grow">
        <div className="name">{med.name_display}</div>
        <div className="meta">
          {med.sig ?? `${med.frequency_per_day}× daily`}
          {med.indication ? ` · for ${med.indication}` : ""}
        </div>
        {isAnticoag && (
          <div style={{ marginTop: 6 }}>
            <span className="chip anticoagulant">Blood thinner — don't skip</span>
          </div>
        )}

        <div className="dose-row">
          {med.doses_today.map((d) => (
            <div key={d.dose_index} className="dose-slot">
              <span className="time">{d.reminder_time ?? ""}</span>
              <button
                type="button"
                className={d.status === "taken" ? "mini taken" : "mini"}
                disabled={busy === d.dose_index}
                onClick={() => mark(d.dose_index, "taken")}
              >
                {d.status === "taken" ? "✓ Taken" : "Taken"}
              </button>
              <button
                type="button"
                className={d.status === "missed" ? "mini missed" : "mini"}
                disabled={busy === d.dose_index}
                onClick={() => mark(d.dose_index, "missed")}
              >
                {d.status === "missed" ? "Missed" : "Missed"}
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function Meds({ onRecorded }: { onRecorded: () => void }) {
  const [data, setData] = useState<MedListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ ack: string; alerted: boolean } | null>(null);

  function load() {
    fetchMedications()
      .then(setData)
      .catch((e) => setError(String(e.message ?? e)));
  }

  useEffect(load, []);

  if (error && !data) return <div className="screen"><ErrorNote error={error} /></div>;
  if (!data) return <Loading what="your medicines" />;

  const a = data.adherence;
  const anticoags = data.medications.filter((m) => m.med_class === "anticoagulant");
  const others = data.medications.filter((m) => m.med_class !== "anticoagulant");

  return (
    <div className="screen">
      <h2>Your medicines</h2>
      <p className="lede">Tap as you take them. Your care team sees missed doses.</p>

      {notice && (
        <div className={notice.alerted ? "notice warn" : "notice"}>{notice.ack}</div>
      )}

      <div className="stats">
        <Stat value={`${a.pct ?? 0}%`} label="All medicines" />
        <Stat value={`${a.anticoagulant_pct ?? 0}%`} label="Blood thinner" />
        <Stat value={a.missed} label="Doses missed" />
      </div>

      {anticoags.length > 0 && (
        <Card title="Blood thinner">
          {anticoags.map((m) => (
            <MedRow
              key={m.id}
              med={m}
              onRecorded={(ack, alerted) => {
                setNotice({ ack, alerted });
                onRecorded();
                load();
              }}
            />
          ))}
          <div className="sub" style={{ marginTop: 10 }}>
            This prevents blood clots after your surgery. If you miss a dose, take
            the next one at the usual time — never double up.
          </div>
        </Card>
      )}

      {others.length > 0 && (
        <Card title="Other medicines">
          {others.map((m) => (
            <MedRow
              key={m.id}
              med={m}
              onRecorded={(ack, alerted) => {
                setNotice({ ack, alerted });
                onRecorded();
                load();
              }}
            />
          ))}
        </Card>
      )}

      <div className="sub" style={{ textAlign: "center", fontSize: 13 }}>
        Reminders show in the app only — this prototype doesn't text or call you.
      </div>
    </div>
  );
}
