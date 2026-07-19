import { useState } from "react";
import { QueueItem, ResolveAction, resolveQueueItem } from "./api";

type Props = {
  items: QueueItem[];
  loading: boolean;
  error: string | null;
  selectedId: number | null;
  onSelect: (item: QueueItem) => void;
  onResolved: (id: number) => void;
};

const ACTIONS: { action: ResolveAction; label: string; primary?: boolean }[] = [
  { action: "call_caregiver", label: "Call caregiver", primary: true },
  { action: "call_patient", label: "Call patient" },
  { action: "mark_resolved", label: "Resolve with note…" },
];

export default function TriageQueue({
  items,
  loading,
  error,
  selectedId,
  onSelect,
  onResolved,
}: Props) {
  const [busyId, setBusyId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const selected = items.find((i) => i.id === selectedId) ?? null;

  async function resolve(item: QueueItem, action: ResolveAction) {
    let note: string | undefined;
    if (action === "mark_resolved") {
      const entered = window.prompt("Resolution note", "Follow-up complete");
      if (entered === null) return;
      note = entered.trim() || "Follow-up complete";
    }
    setBusyId(item.id);
    setActionError(null);
    try {
      await resolveQueueItem(item.id, action, note);
      onResolved(item.id);
    } catch (err) {
      setActionError(String(err));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section className="panel triage" aria-labelledby="queue-title">
      <div className="panel-h">
        <h2 id="queue-title">Triage queue</h2>
        <span className="dtag">D7 · framework</span>
      </div>

      {loading && <div className="queue-empty">Loading queue…</div>}
      {error && <div className="queue-empty error-inline">{error}</div>}
      {!loading && !error && items.length === 0 && (
        <div className="queue-empty">No open alerts.</div>
      )}

      <div className="queue-list">
        {items.map((item) => (
          <div
            key={item.id}
            className={`queue-item${selectedId === item.id ? " selected" : ""}`}
            role="button"
            tabIndex={0}
            onClick={() => onSelect(item)}
            onKeyDown={(ev) => {
              if (ev.key === "Enter" || ev.key === " ") {
                ev.preventDefault();
                onSelect(item);
              }
            }}
          >
            <div className={`sev ${item.severity === "red" ? "red" : "yel"}`}>
              {item.severity === "red" ? "NOW" : "WATCH"}
            </div>
            <div>
              <div className="q-title">{item.title}</div>
              <div className="q-sub">
                {item.patient_name ?? "Patient"}
                {item.fin ? ` · FIN ${item.fin}` : ""}
                {item.summary ? ` · ${item.summary}` : ""}
              </div>
              {item.assigned_role && (
                <div className="q-assign">Assign: {item.assigned_role}</div>
              )}
            </div>
            <div className="q-meta">{item.kind.replace(/_/g, " ")}</div>
          </div>
        ))}
      </div>

      {selected && (
        <div className="queue-actions">
          <div className="queue-actions-label">Resolve · {selected.title}</div>
          {actionError && <div className="error-inline">{actionError}</div>}
          <div className="actions">
            {ACTIONS.map((a) => (
              <button
                key={a.action}
                type="button"
                className={a.primary ? "primary" : undefined}
                disabled={busyId === selected.id}
                onClick={() => resolve(selected, a.action)}
              >
                {a.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
