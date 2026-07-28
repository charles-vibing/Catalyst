/**
 * Daily check-in (A3) — one screen, target under 60 seconds.
 *
 * Six taps end to end: pain, mood, sleep, mobility, weight-bearing, exercises.
 * Everything is a tap target; the only typing is an optional note. Field
 * definitions come from the API so the vocabulary lives in one place
 * (backend/app/routers/checkin.py).
 *
 * Re-submitting the same day is allowed and upserts — patients correct
 * themselves, and refusing the edit would just produce wrong data.
 */

import { useEffect, useState } from "react";
import {
  Checkin,
  TodayResponse,
  fetchCheckinHistory,
  fetchToday,
  submitCheckin,
} from "./api";
import { Card, Choices, ErrorNote, Field, Loading, Scale, shortDate } from "./components/ui";

export default function CheckIn({ onSubmitted }: { onSubmitted: () => void }) {
  const [data, setData] = useState<TodayResponse | null>(null);
  const [history, setHistory] = useState<Checkin[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<{
    ack: string;
    alerts: number;
    met: string[];
  } | null>(null);

  const [pain, setPain] = useState<number | null>(null);
  const [mood, setMood] = useState<string | null>(null);
  const [sleep, setSleep] = useState<string | null>(null);
  const [mobility, setMobility] = useState<string | null>(null);
  const [weightBearing, setWeightBearing] = useState<string | null>(null);
  const [ptDone, setPtDone] = useState<boolean | null>(null);
  const [note, setNote] = useState("");

  function hydrate(c: Checkin | null) {
    if (!c) return;
    setPain(c.pain_score);
    setMood(c.mood);
    setSleep(c.sleep_quality);
    setMobility(c.mobility_status);
    setWeightBearing(c.weight_bearing_status);
    setPtDone(c.pt_completed);
    setNote(c.note ?? "");
  }

  function load() {
    fetchToday()
      .then((d) => {
        setData(d);
        hydrate(d.checkin);
      })
      .catch((e) => setError(String(e.message ?? e)));
    fetchCheckinHistory(14).then(setHistory).catch(() => setHistory([]));
  }

  useEffect(load, []);

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      const res = await submitCheckin({
        pain_score: pain,
        mood,
        sleep_quality: sleep,
        mobility_status: mobility,
        weight_bearing_status: weightBearing,
        pt_completed: ptDone,
        note: note.trim() || null,
      });
      setResult({
        ack: res.acknowledgement,
        alerts: res.alerts.length,
        met: res.milestones_met,
      });
      onSubmitted();
      load();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setSaving(false);
    }
  }

  if (error && !data) return <div className="screen"><ErrorNote error={error} /></div>;
  if (!data) return <Loading what="your check-in" />;

  const f = data.form;
  const painValues = history
    .slice()
    .reverse()
    .map((h) => h.pain_score ?? 0);

  return (
    <div className="screen">
      <h2>How are you today?</h2>
      <p className="lede">
        {data.already_submitted
          ? "You've checked in today — you can change your answers."
          : "Takes less than a minute. Your care team sees this."}
        {data.streak_days > 1 && ` ${data.streak_days} days in a row.`}
      </p>

      {error && <ErrorNote error={error} />}

      {result && (
        <div className={result.alerts > 0 ? "notice warn" : "notice"}>
          {result.ack}
          {result.met.length > 0 && (
            <div className="met-list">Goal reached: {result.met.join(", ")}</div>
          )}
        </div>
      )}

      <Field label={f.pain.label}>
        <Scale
          value={pain}
          min={f.pain.min ?? 0}
          max={f.pain.max ?? 10}
          lowLabel="No pain"
          highLabel="Worst pain"
          onChange={setPain}
        />
      </Field>

      <Field label={f.mood.label}>
        <Choices
          options={f.mood.options ?? []}
          labels={{ good: "Good", ok: "OK", low: "Low", anxious: "Anxious" }}
          value={mood}
          onChange={setMood}
        />
      </Field>

      <Field label={f.sleep_quality.label}>
        <Choices
          options={f.sleep_quality.options ?? []}
          labels={{ good: "Well", fair: "So-so", poor: "Badly" }}
          value={sleep}
          onChange={setSleep}
        />
      </Field>

      <Field label={f.mobility_status.label}>
        <Choices
          options={f.mobility_status.options ?? []}
          labels={f.mobility_status.labels}
          value={mobility}
          onChange={setMobility}
          stacked
        />
      </Field>

      <Field
        label={f.weight_bearing_status.label}
        hint={
          f.weight_bearing_status.order_text
            ? `Your surgeon's instruction: ${f.weight_bearing_status.order_text}`
            : null
        }
      >
        <Choices
          options={f.weight_bearing_status.options ?? []}
          labels={f.weight_bearing_status.labels}
          value={weightBearing}
          onChange={setWeightBearing}
          stacked
        />
      </Field>

      <Field label={f.pt_completed.label}>
        <Choices
          options={["yes", "no"]}
          labels={{ yes: "Yes, I did them", no: "Not today" }}
          value={ptDone === null ? null : ptDone ? "yes" : "no"}
          onChange={(v) => setPtDone(v === "yes")}
        />
      </Field>

      <Field label="Anything else?" hint="Optional.">
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Anything you want your care team to know"
        />
      </Field>

      <div className="sticky-submit">
        <button
          type="button"
          className="btn primary block"
          disabled={saving}
          onClick={submit}
        >
          {saving ? "Sending…" : data.already_submitted ? "Update today's check-in" : "Send check-in"}
        </button>
      </div>

      {painValues.length > 1 && (
        <Card title="Your pain over the last two weeks">
          <div className="trend">
            {painValues.map((v, i) => (
              <div
                key={i}
                className="bar"
                style={{ height: `${Math.max(6, (v / 10) * 100)}%` }}
                title={`${v}/10`}
              />
            ))}
          </div>
          <div className="scale-ends">
            <span>{shortDate(history[history.length - 1]?.checkin_date ?? null)}</span>
            <span>Today</span>
          </div>
        </Card>
      )}
    </div>
  );
}
