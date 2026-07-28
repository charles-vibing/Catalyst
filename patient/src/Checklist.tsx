/**
 * Phase-gated checklists (A9): SNF discharge readiness and home safety.
 *
 * Which checklists appear is decided server-side from phase + disposition
 * (backend/app/catalog.py), so a home-discharge patient never sees the facility
 * readiness list.
 *
 * Answers save as you go. A "no" on a critical item is framed as something the
 * care team will help with rather than a failure — that framing is the whole
 * reason a patient answers honestly, and honest answers are the point.
 */

import { useEffect, useState } from "react";
import {
  AvailableChecklists,
  ChecklistResponse,
  fetchChecklist,
  fetchChecklists,
  saveChecklist,
} from "./api";
import { Card, Choices, ErrorNote, Loading } from "./components/ui";

const ANSWER_LABELS: Record<string, string> = {
  yes: "Yes",
  no: "Not yet",
  na: "Doesn't apply",
};

function ChecklistDetail({
  code,
  onBack,
  onSaved,
}: {
  code: string;
  onBack: () => void;
  onSaved: () => void;
}) {
  const [data, setData] = useState<ChecklistResponse | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<{ ack: string; flagged: string[] } | null>(null);

  function load() {
    fetchChecklist(code)
      .then((d) => {
        setData(d);
        setAnswers(
          Object.fromEntries(
            d.items.filter((i) => i.answer).map((i) => [i.item_code, i.answer as string]),
          ),
        );
      })
      .catch((e) => setError(String(e.message ?? e)));
  }

  useEffect(load, [code]);

  async function save() {
    if (!data) return;
    setSaving(true);
    setError(null);
    try {
      const res = await saveChecklist(
        code,
        Object.entries(answers).map(([item_code, answer]) => ({ item_code, answer })),
      );
      setResult({ ack: res.acknowledgement, flagged: res.flagged_items });
      onSaved();
      load();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setSaving(false);
    }
  }

  if (error && !data) return <div className="screen"><ErrorNote error={error} /></div>;
  if (!data) return <Loading what="the checklist" />;

  const answeredCount = Object.keys(answers).length;

  return (
    <div className="screen">
      <button type="button" className="btn" onClick={onBack} style={{ marginBottom: 16 }}>
        ← Back
      </button>

      <h2>{data.title}</h2>
      <p className="lede">{data.intro}</p>

      {!data.unlocked && (
        <div className="notice warn">
          This list isn't active for you right now — you can look but not change it.
        </div>
      )}

      {result && (
        <div className={result.flagged.length > 0 ? "notice warn" : "notice"}>
          {result.ack}
          {result.flagged.length > 0 && (
            <div className="met-list">
              Flagged for your team: {result.flagged.join("; ")}
            </div>
          )}
        </div>
      )}

      {error && <ErrorNote error={error} />}

      <div className="progress-bar">
        <span style={{ width: `${(answeredCount / data.items.length) * 100}%` }} />
      </div>
      <div className="sub" style={{ fontSize: 13, marginBottom: 16 }}>
        {answeredCount} of {data.items.length} answered
      </div>

      <Card>
        {data.items.map((item) => (
          <div key={item.item_code} className="check-item">
            <div className="q">
              {item.label}
              {item.critical && <span className="req">important</span>}
            </div>
            {item.help_text && <div className="help">{item.help_text}</div>}
            <Choices
              options={["yes", "no", "na"]}
              labels={ANSWER_LABELS}
              value={answers[item.item_code] ?? null}
              onChange={(v) =>
                data.unlocked && setAnswers({ ...answers, [item.item_code]: v })
              }
            />
          </div>
        ))}
      </Card>

      {data.unlocked && (
        <div className="sticky-submit">
          <button
            type="button"
            className="btn primary block"
            disabled={saving || answeredCount === 0}
            onClick={save}
          >
            {saving ? "Saving…" : "Save answers"}
          </button>
        </div>
      )}
    </div>
  );
}

export default function Checklist({ onSaved }: { onSaved: () => void }) {
  const [list, setList] = useState<AvailableChecklists | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  function load() {
    fetchChecklists()
      .then(setList)
      .catch((e) => setError(String(e.message ?? e)));
  }

  useEffect(load, []);

  if (selected) {
    return (
      <ChecklistDetail
        code={selected}
        onBack={() => {
          setSelected(null);
          load();
        }}
        onSaved={onSaved}
      />
    );
  }

  if (error && !list) return <div className="screen"><ErrorNote error={error} /></div>;
  if (!list) return <Loading what="your checklists" />;

  return (
    <div className="screen">
      <h2>Getting set up</h2>
      <p className="lede">
        Short checklists for where you are in your recovery. Your care team sees
        what still needs sorting.
      </p>

      {list.available.length === 0 && (
        <div className="empty">Nothing to check off at this stage.</div>
      )}

      {list.available.map((c) => (
        <button
          key={c.checklist_code}
          type="button"
          className="patient-pick"
          onClick={() => setSelected(c.checklist_code)}
        >
          <div className="pname">{c.title}</div>
          <div className="pmeta">
            {c.progress.answered === 0
              ? "Not started"
              : c.progress.complete
                ? "✓ All the important things are in place"
                : `${c.progress.answered} of ${c.progress.total} answered` +
                  (c.progress.blockers.length > 0
                    ? ` · ${c.progress.blockers.length} still to sort`
                    : "")}
          </div>
        </button>
      ))}
    </div>
  );
}
