/**
 * Red-flag symptom triage (A3 severity routing).
 *
 * Six categories, each a short structured intake. Scoring happens server-side
 * (backend/app/rules.py) — never in the browser, so the guidance a patient sees
 * and the alert the navigator gets can't diverge.
 *
 * The result screen leads with what to DO, not with a severity label: "Call 911
 * now" is more use to a frightened patient than "red".
 */

import { useEffect, useState } from "react";
import {
  RedFlagCategory,
  RedFlagQuestion,
  RedFlagQuestionsResponse,
  RedFlagReport,
  RedFlagSubmitResponse,
  fetchRedFlagQuestions,
  fetchRedFlags,
  submitRedFlag,
} from "./api";
import {
  Card,
  Choices,
  ErrorNote,
  Field,
  GuidanceBox,
  Loading,
  Scale,
  prettify,
  shortDate,
} from "./components/ui";

/** Whole-number ranges of 10 or fewer steps get tap buttons; anything else
 *  (e.g. temperature 96–105 in 0.1 increments) gets a number field. */
function isTappableScale(q: RedFlagQuestion): boolean {
  const span = (q.max ?? 10) - (q.min ?? 0);
  return span <= 10 && (q.step ?? 1) >= 1;
}

const CATEGORY_GLYPHS: Record<string, string> = {
  fever: "🌡",
  dvt: "🦵",
  pe: "🫁",
  wound: "🩹",
  pain: "⚡",
  fall: "⚠",
};

export default function RedFlag({ onSubmitted }: { onSubmitted: () => void }) {
  const [defs, setDefs] = useState<RedFlagQuestionsResponse | null>(null);
  const [past, setPast] = useState<RedFlagReport[]>([]);
  const [active, setActive] = useState<RedFlagCategory | null>(null);
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [result, setResult] = useState<RedFlagSubmitResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function load() {
    fetchRedFlagQuestions()
      .then(setDefs)
      .catch((e) => setError(String(e.message ?? e)));
    fetchRedFlags().then(setPast).catch(() => setPast([]));
  }

  useEffect(load, []);

  function open(cat: RedFlagCategory) {
    setActive(cat);
    setAnswers({});
    setResult(null);
    setError(null);
  }

  async function submit() {
    if (!active) return;
    setSaving(true);
    setError(null);
    try {
      const res = await submitRedFlag(active.category, answers);
      setResult(res);
      onSubmitted();
      fetchRedFlags().then(setPast).catch(() => undefined);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setSaving(false);
    }
  }

  if (!defs && !error) return <Loading what="the symptom checker" />;
  if (error && !defs) return <div className="screen"><ErrorNote error={error} /></div>;

  // --- result screen ---
  if (result) {
    return (
      <div className="screen">
        <h2>What to do</h2>
        <GuidanceBox
          headline={result.guidance.headline}
          body={result.guidance.body}
          urgency={result.guidance.urgency}
          contact={result.emergency_contact}
        />
        {result.report.reasons.length > 0 && (
          <Card title="What you told us">
            {result.report.reasons.map((r, i) => (
              <div key={i} className="sub">
                • {r}
              </div>
            ))}
          </Card>
        )}
        {result.care_team_notified && (
          <div className="notice">
            Your care team at Memorial General has been notified and can see this.
          </div>
        )}
        <div className="btn-row">
          <button
            type="button"
            className="btn primary block"
            onClick={() => {
              setResult(null);
              setActive(null);
            }}
          >
            Done
          </button>
        </div>
      </div>
    );
  }

  // --- intake screen ---
  if (active) {
    return (
      <div className="screen">
        <h2>{active.title}</h2>
        <p className="lede">{active.prompt}</p>
        {error && <ErrorNote error={error} />}

        {active.questions.map((q) => (
          <Field
            key={q.key}
            label={q.label}
            hint={q.optional ? "Optional — skip if you don't know" : null}
          >
            {q.type === "bool" && (
              <Choices
                options={["yes", "no"]}
                labels={{ yes: "Yes", no: "No" }}
                value={
                  answers[q.key] === undefined ? null : answers[q.key] ? "yes" : "no"
                }
                onChange={(v) => setAnswers({ ...answers, [q.key]: v === "yes" })}
              />
            )}
            {q.type === "choice" && (
              <Choices
                options={q.options ?? []}
                labels={Object.fromEntries(
                  (q.options ?? []).map((o) => [o, prettify(o)]),
                )}
                value={(answers[q.key] as string) ?? null}
                onChange={(v) => setAnswers({ ...answers, [q.key]: v })}
                stacked
              />
            )}
            {/* A tappable 0–10 scale for small integer ranges (pain); a number
                field for wide or fractional ones (temperature in °F). */}
            {q.type === "scale" &&
              (isTappableScale(q) ? (
                <Scale
                  value={(answers[q.key] as number) ?? null}
                  min={q.min ?? 0}
                  max={q.max ?? 10}
                  onChange={(v) => setAnswers({ ...answers, [q.key]: v })}
                />
              ) : (
                <input
                  type="number"
                  inputMode="decimal"
                  step={q.step ?? 1}
                  min={q.min}
                  max={q.max}
                  value={(answers[q.key] as number) ?? ""}
                  onChange={(e) =>
                    setAnswers({
                      ...answers,
                      [q.key]:
                        e.target.value === "" ? undefined : Number(e.target.value),
                    })
                  }
                  placeholder={`${q.min}–${q.max}`}
                />
              ))}
          </Field>
        ))}

        <div className="btn-row">
          <button type="button" className="btn" onClick={() => setActive(null)}>
            Back
          </button>
          <button
            type="button"
            className="btn danger"
            style={{ flex: 1 }}
            disabled={saving}
            onClick={submit}
          >
            {saving ? "Checking…" : "Get advice"}
          </button>
        </div>
      </div>
    );
  }

  // --- category picker ---
  return (
    <div className="screen">
      <h2>Something's wrong</h2>
      <p className="lede">
        Pick what's happening. We'll tell you what to do and let your care team
        know. If you think it's an emergency, call 911 first.
      </p>

      {defs?.categories.map((cat) => (
        <button
          key={cat.category}
          type="button"
          className="patient-pick"
          onClick={() => open(cat)}
        >
          <div className="pname">
            <span aria-hidden="true" style={{ marginRight: 8 }}>
              {CATEGORY_GLYPHS[cat.category] ?? "•"}
            </span>
            {cat.title}
          </div>
          <div className="pmeta">{cat.prompt}</div>
        </button>
      ))}

      {past.length > 0 && (
        <Card title="What you've reported before">
          {past.slice(0, 5).map((r) => (
            <div key={r.id} className="row">
              <div className="grow">
                <div className="name">{r.title}</div>
                <div className="meta">
                  {shortDate(r.reported_at)}
                  {r.reasons[0] ? ` · ${r.reasons[0]}` : ""}
                </div>
              </div>
              <span className={`chip ${r.severity === "red" ? "anticoagulant" : "due"}`}>
                {r.severity === "red" ? "Urgent" : "Watch"}
              </span>
            </div>
          ))}
        </Card>
      )}
    </div>
  );
}
