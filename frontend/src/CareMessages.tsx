/**
 * Care-team message inbox (provider side of A5/A8).
 *
 * Threads come from the patient companion app. Replying here lands back in the
 * patient's thread and flips the unread counters, so the loop closes without
 * anyone picking up a phone.
 *
 * Selecting a thread also selects that episode in the roster, so the navigator
 * reads the message with the chart beside it.
 */

import { useEffect, useState } from "react";
import { CareThread, closeThread, fetchInbox, replyToThread } from "./api";

function fmtStamp(iso: string | null): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  const t = iso.slice(11, 16);
  return t ? `${m}/${d} ${t}` : `${m}/${d}/${y}`;
}

export default function CareMessages({
  onSelectEpisode,
}: {
  onSelectEpisode: (fin: string) => void;
}) {
  const [threads, setThreads] = useState<CareThread[]>([]);
  const [meta, setMeta] = useState<{ total: number; unread_threads: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [openId, setOpenId] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    setLoading(true);
    fetchInbox("open")
      .then((d) => {
        setThreads(d.threads);
        setMeta(d.meta);
      })
      .catch((err) => setError(String(err)))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  async function send(threadId: number) {
    if (!draft.trim()) return;
    setBusy(true);
    try {
      await replyToThread(threadId, draft.trim());
      setDraft("");
      load();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function resolve(threadId: number) {
    setBusy(true);
    try {
      await closeThread(threadId);
      setOpenId(null);
      load();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel messages" aria-labelledby="msg-title">
      <div className="panel-h">
        <h2 id="msg-title">Patient messages</h2>
        <span className="dtag">
          {meta ? `${meta.unread_threads} unread · ${meta.total} open` : "…"}
        </span>
      </div>

      {loading && <div className="queue-empty">Loading messages…</div>}
      {error && <div className="queue-empty error-inline">{error}</div>}
      {!loading && !error && threads.length === 0 && (
        <div className="queue-empty">No open patient messages.</div>
      )}

      <div className="msg-list">
        {threads.map((t) => (
          <div key={t.id} className={openId === t.id ? "msg-thread open" : "msg-thread"}>
            <button
              type="button"
              className="msg-head"
              onClick={() => {
                setOpenId(openId === t.id ? null : t.id);
                setDraft("");
                if (t.fin) onSelectEpisode(t.fin);
              }}
            >
              <span className="msg-who">
                {t.unread_provider > 0 && <span className="msg-unread" aria-label="unread" />}
                {t.patient_name ?? `Patient ${t.patient_id}`}
              </span>
              <span className="msg-subject">{t.subject}</span>
              <span className="msg-when">{fmtStamp(t.last_message_at)}</span>
            </button>

            {openId === t.id ? (
              <div className="msg-body">
                {t.messages.map((m) => (
                  <div
                    key={m.id}
                    className={
                      m.sender_role === "care_team" ? "msg-bubble ours" : "msg-bubble theirs"
                    }
                  >
                    <div className="msg-meta">
                      {m.sender_role === "care_team"
                        ? "Care team"
                        : m.sender_role === "caregiver"
                          ? "Caregiver"
                          : "Patient"}{" "}
                      · {fmtStamp(m.sent_at)}
                    </div>
                    {m.body}
                  </div>
                ))}
                <textarea
                  className="msg-input"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder="Reply to the patient…"
                  rows={3}
                />
                <div className="actions">
                  <button
                    type="button"
                    className="primary"
                    disabled={busy || !draft.trim()}
                    onClick={() => send(t.id)}
                  >
                    Send reply
                  </button>
                  <button type="button" disabled={busy} onClick={() => resolve(t.id)}>
                    Close thread
                  </button>
                </div>
              </div>
            ) : (
              <div className="msg-preview">{t.last_preview}</div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
