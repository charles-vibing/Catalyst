/**
 * PT exercise library and logging (A5 / A10).
 *
 * Exercises are phase-filtered server-side, and each carries the weight-bearing
 * caveat that matters for hip fracture — a patient told "partial weight bearing"
 * needs that on the exercise itself, not buried in a discharge packet.
 *
 * Video URLs are placeholders in the MVP; the tile shows what would play there
 * rather than pretending to be a player (see TODO.md).
 */

import { useEffect, useState } from "react";
import { Exercise, ExerciseListResponse, fetchExercises, logExercise } from "./api";
import { Card, Choices, ErrorNote, Loading } from "./components/ui";

const DIFFICULTY_LABELS: Record<string, string> = {
  easy: "Easy",
  ok: "About right",
  hard: "Hard",
  too_hard: "Too hard",
};

function ExerciseCard({
  ex,
  onLogged,
}: {
  ex: Exercise;
  onLogged: (ack: string, met: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [difficulty, setDifficulty] = useState<string | null>(ex.difficulty);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function log() {
    setSaving(true);
    setError(null);
    try {
      const res = await logExercise({
        exercise_code: ex.code,
        sets_done: ex.default_sets,
        reps_done: ex.default_reps,
        completed: true,
        difficulty,
      });
      onLogged(res.acknowledgement, res.milestones_met);
      setOpen(false);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card">
      <div className="row" style={{ paddingTop: 0, borderBottom: 0 }}>
        <div className="grow">
          <div className="name">{ex.name}</div>
          <div className="meta">
            {ex.default_sets} sets of {ex.default_reps}
            {ex.logged_today && " · done today"}
          </div>
        </div>
        {ex.logged_today && <span className="chip ok">✓ Done</span>}
      </div>

      {!open ? (
        <div className="btn-row">
          <button type="button" className="btn" onClick={() => setOpen(true)}>
            How to do it
          </button>
          {!ex.logged_today && (
            <button type="button" className="btn primary" style={{ flex: 1 }} onClick={log}>
              Mark done
            </button>
          )}
        </div>
      ) : (
        <>
          <div className="video-placeholder">
            Video: {ex.name}
            <br />
            (placeholder — no media in this prototype)
          </div>
          <p className="sub" style={{ marginBottom: 10 }}>
            {ex.description}
          </p>
          {ex.weight_bearing_note && (
            <div className="notice warn" style={{ fontSize: 14 }}>
              {ex.weight_bearing_note}
            </div>
          )}
          {error && <ErrorNote error={error} />}
          <div className="field" style={{ marginBottom: 12 }}>
            <span className="field-label">How did it feel?</span>
            <Choices
              options={Object.keys(DIFFICULTY_LABELS)}
              labels={DIFFICULTY_LABELS}
              value={difficulty}
              onChange={setDifficulty}
            />
          </div>
          <div className="btn-row">
            <button type="button" className="btn" onClick={() => setOpen(false)}>
              Close
            </button>
            <button
              type="button"
              className="btn primary"
              style={{ flex: 1 }}
              disabled={saving}
              onClick={log}
            >
              {saving ? "Saving…" : ex.logged_today ? "Update" : "Mark done"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

export default function Exercises({ onLogged }: { onLogged: () => void }) {
  const [data, setData] = useState<ExerciseListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ ack: string; met: string[] } | null>(null);

  function load() {
    fetchExercises()
      .then(setData)
      .catch((e) => setError(String(e.message ?? e)));
  }

  useEffect(load, []);

  if (error && !data) return <div className="screen"><ErrorNote error={error} /></div>;
  if (!data) return <Loading what="your exercises" />;

  const doneToday = data.exercises.filter((e) => e.logged_today).length;

  return (
    <div className="screen">
      <h2>Your exercises</h2>
      <p className="lede">
        {doneToday > 0
          ? `${doneToday} done today. `
          : "Nothing logged yet today. "}
        Your therapist sees what you log.
      </p>

      {notice && (
        <div className="notice">
          {notice.ack}
          {notice.met.length > 0 && (
            <div className="met-list">Goal reached: {notice.met.join(", ")}</div>
          )}
        </div>
      )}

      {data.prescription.weight_bearing && (
        <Card title="Your weight-bearing instruction" tinted>
          <div className="sub">{data.prescription.weight_bearing}</div>
          {data.prescription.therapist && (
            <div className="sub" style={{ marginTop: 6 }}>
              From {data.prescription.therapist}
            </div>
          )}
        </Card>
      )}

      {data.prescription.goals.length > 0 && (
        <Card title="What you're working toward">
          {data.prescription.goals.map((g, i) => (
            <div key={i} className="sub">
              • {g}
            </div>
          ))}
        </Card>
      )}

      {data.exercises.map((ex) => (
        <ExerciseCard
          key={ex.code}
          ex={ex}
          onLogged={(ack, met) => {
            setNotice({ ack, met });
            onLogged();
            load();
          }}
        />
      ))}
    </div>
  );
}
