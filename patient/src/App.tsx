/**
 * Patient companion app shell.
 *
 * Three states: not signed in (patient picker), signed in but not enrolled
 * (onboarding), enrolled (tabbed app). Tab state is local — no router, matching
 * the dashboard's approach.
 *
 * `reload` is passed to every screen so a write anywhere refreshes the shared
 * timeline data (milestone progress, unread counts, alert badges) without a
 * global store.
 */

import { useCallback, useEffect, useState } from "react";
import Appointments from "./Appointments";
import CheckIn from "./CheckIn";
import Checklist from "./Checklist";
import Exercises from "./Exercises";
import Login from "./Login";
import Meds from "./Meds";
import Messages from "./Messages";
import Onboarding from "./Onboarding";
import RedFlag from "./RedFlag";
import Timeline from "./Timeline";
import {
  MeResponse,
  ThreadListResponse,
  TimelineResponse,
  clearPatientId,
  fetchMe,
  fetchThreads,
  fetchTimeline,
  getPatientId,
} from "./api";
import { ErrorNote, Loading } from "./components/ui";

type Tab =
  | "home"
  | "checkin"
  | "exercises"
  | "meds"
  | "more"
  | "symptoms"
  | "appointments"
  | "messages"
  | "checklists";

const TABS: { id: Tab; label: string; glyph: string }[] = [
  { id: "home", label: "Recovery", glyph: "◈" },
  { id: "checkin", label: "Check in", glyph: "✎" },
  { id: "exercises", label: "Exercises", glyph: "◎" },
  { id: "meds", label: "Medicines", glyph: "◍" },
  { id: "more", label: "More", glyph: "⋯" },
];

const ALL_TABS: Tab[] = [
  "home", "checkin", "exercises", "meds", "more",
  "symptoms", "appointments", "messages", "checklists",
];

/** `?tab=checkin` opens straight to a screen — handy for demo links. */
function initialTab(): Tab {
  const t = new URLSearchParams(window.location.search).get("tab");
  return t && (ALL_TABS as string[]).includes(t) ? (t as Tab) : "home";
}

export default function App() {
  const [signedIn, setSignedIn] = useState(getPatientId() !== null);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [timeline, setTimeline] = useState<TimelineResponse | null>(null);
  const [threads, setThreads] = useState<ThreadListResponse | null>(null);
  const [tab, setTab] = useState<Tab>(initialTab);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    if (!getPatientId()) return;
    setError(null);
    fetchMe()
      .then((m) => {
        setMe(m);
        if (m.enrolled) {
          fetchTimeline().then(setTimeline).catch(() => undefined);
          fetchThreads().then(setThreads).catch(() => undefined);
        }
      })
      .catch((e) => setError(String(e.message ?? e)));
  }, []);

  useEffect(() => {
    if (signedIn) reload();
  }, [signedIn, reload]);

  function signOut() {
    clearPatientId();
    setMe(null);
    setTimeline(null);
    setThreads(null);
    setTab("home");
    setSignedIn(false);
  }

  if (!signedIn) {
    return <Login onSignedIn={() => setSignedIn(true)} />;
  }

  if (error) {
    return (
      <div className="app">
        <div className="screen">
          <ErrorNote error={error} />
          <button type="button" className="btn block" onClick={signOut}>
            Sign in as someone else
          </button>
        </div>
      </div>
    );
  }

  if (!me) return <Loading what="your recovery plan" />;

  // Onboarding gate — everything else requires an enrollment record.
  if (!me.enrolled) {
    return (
      <div className="app">
        <div className="synthetic-banner">Synthetic demo data — not a real patient</div>
        <Onboarding me={me} onDone={reload} />
      </div>
    );
  }

  const firstName = me.episode.patient_name.split(",")[1]?.trim() ?? me.episode.patient_name;
  const unread = threads?.meta.unread_total ?? 0;

  return (
    <div className="app">
      <div className="topbar">
        <div>
          <h1>My Recovery</h1>
          <div className="who">
            {firstName} · {me.episode.hospital}
          </div>
        </div>
        <button type="button" onClick={signOut}>
          Sign out
        </button>
      </div>
      <div className="synthetic-banner">
        Synthetic demo data — as-of {me.meta.as_of}
        {me.meta.as_of_mode === "frozen" ? " (frozen)" : ""}
      </div>

      {tab === "home" &&
        (timeline ? (
          <Timeline data={timeline} onGoTo={(t) => setTab(t as Tab)} />
        ) : (
          <Loading what="your timeline" />
        ))}

      {tab === "checkin" && <CheckIn onSubmitted={reload} />}
      {tab === "exercises" && <Exercises onLogged={reload} />}
      {tab === "meds" && <Meds onRecorded={reload} />}
      {tab === "symptoms" && <RedFlag onSubmitted={reload} />}
      {tab === "appointments" && <Appointments onChanged={reload} />}
      {tab === "messages" && <Messages onChanged={reload} />}
      {tab === "checklists" && <Checklist onSaved={reload} />}

      {tab === "more" && (
        <div className="screen">
          <h2>More</h2>
          <p className="lede">Everything else in your recovery plan.</p>

          <button
            type="button"
            className="patient-pick"
            onClick={() => setTab("symptoms")}
          >
            <div className="pname">Something's wrong</div>
            <div className="pmeta">
              Report a symptom and get advice on what to do
            </div>
          </button>

          <button
            type="button"
            className="patient-pick"
            onClick={() => setTab("appointments")}
          >
            <div className="pname">Appointments</div>
            <div className="pmeta">Surgeon, primary care, therapy and home visits</div>
          </button>

          <button
            type="button"
            className="patient-pick"
            onClick={() => setTab("messages")}
          >
            <div className="pname">
              Message your care team
              {unread > 0 && (
                <span className="chip due" style={{ marginLeft: 8 }}>
                  {unread} new
                </span>
              )}
            </div>
            <div className="pmeta">Ask a question and get a reply</div>
          </button>

          <button
            type="button"
            className="patient-pick"
            onClick={() => setTab("checklists")}
          >
            <div className="pname">Checklists</div>
            <div className="pmeta">Home safety and getting-home readiness</div>
          </button>

          <div className="card" style={{ marginTop: 18 }}>
            <h3>Your surgery</h3>
            <div className="sub">{me.enrollment?.confirmed_procedure_text}</div>
            <div className="sub" style={{ marginTop: 8 }}>
              Surgeon: {me.enrollment?.confirmed_surgeon ?? "—"}
            </div>
            <div className="sub">
              Recovering: {me.enrollment?.confirmed_discharge_destination ?? "—"}
            </div>
            <div className="sub">
              Using the app as:{" "}
              {me.enrollment?.relationship === "caregiver" ? "caregiver" : "the patient"}
            </div>
          </div>
        </div>
      )}

      <nav className="tabbar">
        {TABS.map((t) => {
          const active =
            tab === t.id ||
            (t.id === "more" &&
              ["symptoms", "appointments", "messages", "checklists"].includes(tab));
          return (
            <button
              key={t.id}
              type="button"
              className={active ? "active" : undefined}
              onClick={() => setTab(t.id)}
            >
              <span className="glyph" aria-hidden="true">
                {t.glyph}
              </span>
              {t.label}
              {t.id === "more" && unread > 0 && <span className="badge">{unread}</span>}
            </button>
          );
        })}
      </nav>
    </div>
  );
}
