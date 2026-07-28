/**
 * Secure message to care team (A5 / A8).
 *
 * Threaded, and every thread surfaces in the dashboard inbox. The "urgent"
 * toggle is the app's "I need help" affordance — it raises a queue item rather
 * than relying on someone reading the inbox in time.
 *
 * Care-team replies come back into the same thread; opening a thread marks them
 * read so the dashboard's unread badge clears.
 */

import { useEffect, useState } from "react";
import { Thread, ThreadListResponse, fetchThreads, markThreadRead, sendMessage } from "./api";
import { Card, ErrorNote, Loading, shortDate, timeOf } from "./components/ui";

function ThreadView({ t, onRead }: { t: Thread; onRead: (id: number) => void }) {
  const [open, setOpen] = useState(t.unread_patient > 0);
  const [replying, setReplying] = useState(false);
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (open && t.unread_patient > 0) onRead(t.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  async function reply() {
    if (!body.trim()) return;
    setSending(true);
    try {
      await sendMessage({ thread_id: t.id, body });
      setBody("");
      setReplying(false);
      onRead(t.id);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="thread">
      <button type="button" className="thread-head" onClick={() => setOpen(!open)}>
        <span>
          {t.subject}
          {t.unread_patient > 0 && (
            <span className="chip due" style={{ marginLeft: 8 }}>
              New reply
            </span>
          )}
        </span>
        <span style={{ color: "var(--muted)", fontWeight: 500, fontSize: 13 }}>
          {shortDate(t.last_message_at)}
        </span>
      </button>
      {open && (
        <div className="thread-body">
          {t.messages.map((m) => (
            <div
              key={m.id}
              className={m.sender_role === "care_team" ? "bubble theirs" : "bubble mine"}
            >
              <div className="who">
                {m.sender_role === "care_team" ? "Care team" : "You"} ·{" "}
                {shortDate(m.sent_at)} {timeOf(m.sent_at)}
              </div>
              {m.body}
            </div>
          ))}

          {replying ? (
            <>
              <textarea
                value={body}
                onChange={(e) => setBody(e.target.value)}
                placeholder="Write a reply"
              />
              <div className="btn-row" style={{ marginTop: 10 }}>
                <button type="button" className="btn" onClick={() => setReplying(false)}>
                  Cancel
                </button>
                <button
                  type="button"
                  className="btn primary"
                  style={{ flex: 1 }}
                  disabled={sending || !body.trim()}
                  onClick={reply}
                >
                  {sending ? "Sending…" : "Send reply"}
                </button>
              </div>
            </>
          ) : (
            <button type="button" className="btn" onClick={() => setReplying(true)}>
              Reply
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default function Messages({ onChanged }: { onChanged: () => void }) {
  const [data, setData] = useState<ThreadListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [composing, setComposing] = useState(false);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [urgent, setUrgent] = useState(false);
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  function load() {
    fetchThreads()
      .then(setData)
      .catch((e) => setError(String(e.message ?? e)));
  }

  useEffect(load, []);

  async function send() {
    if (!body.trim()) return;
    setSending(true);
    setError(null);
    try {
      const res = await sendMessage({
        body,
        subject: subject.trim() || null,
        urgent,
      });
      setNotice(res.acknowledgement);
      setBody("");
      setSubject("");
      setUrgent(false);
      setComposing(false);
      onChanged();
      load();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setSending(false);
    }
  }

  if (error && !data) return <div className="screen"><ErrorNote error={error} /></div>;
  if (!data) return <Loading what="your messages" />;

  return (
    <div className="screen">
      <h2>Your care team</h2>
      <p className="lede">
        Send a question and someone from Memorial General will get back to you.
        For anything urgent, mark it urgent — or call 911 if it's an emergency.
      </p>

      {notice && <div className="notice">{notice}</div>}
      {error && <ErrorNote error={error} />}

      {!composing ? (
        <button
          type="button"
          className="btn primary block"
          onClick={() => setComposing(true)}
        >
          Write a message
        </button>
      ) : (
        <Card title="New message">
          <div className="field">
            <span className="field-label">What's it about?</span>
            <input
              type="text"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder="Optional subject"
            />
          </div>
          <div className="field">
            <span className="field-label">Your message</span>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="Type your question here"
            />
          </div>
          <div className="field">
            <button
              type="button"
              className={urgent ? "choice selected" : "choice"}
              onClick={() => setUrgent(!urgent)}
            >
              {urgent ? "✓ " : ""}This needs attention today
            </button>
          </div>
          <div className="btn-row">
            <button type="button" className="btn" onClick={() => setComposing(false)}>
              Cancel
            </button>
            <button
              type="button"
              className="btn primary"
              style={{ flex: 1 }}
              disabled={sending || !body.trim()}
              onClick={send}
            >
              {sending ? "Sending…" : "Send"}
            </button>
          </div>
        </Card>
      )}

      <div className="spacer" />

      {data.threads.length === 0 && (
        <div className="empty">No messages yet.</div>
      )}
      {data.threads.map((t) => (
        <ThreadView
          key={t.id}
          t={t}
          onRead={(id) => {
            markThreadRead(id)
              .then(() => {
                onChanged();
                load();
              })
              .catch(() => undefined);
          }}
        />
      ))}

      {data.care_team.length > 0 && (
        <Card title="Who's looking after you">
          {data.care_team.map((c, i) => (
            <div key={i} className="row">
              <div className="grow">
                <div className="name">{c.name}</div>
                <div className="meta">{c.role}</div>
              </div>
            </div>
          ))}
        </Card>
      )}
    </div>
  );
}
