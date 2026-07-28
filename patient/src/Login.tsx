/**
 * Demo patient picker — stands in for a login.
 *
 * There is no auth provider in this prototype (see backend/app/auth.py), so
 * "signing in" means choosing which episode to act as. The chosen identifier
 * goes to localStorage and rides every request as X-Catalyst-Patient.
 *
 * Login is agnostic: the same account is used by the patient or a caregiver.
 * Which one is answering is captured during onboarding as `relationship`, not
 * by having two kinds of account (post-MVP — see TODO.md).
 */

import { useEffect, useState } from "react";
import { Candidate, fetchCandidates, setPatientId } from "./api";
import { ErrorNote, Loading, shortDate } from "./components/ui";

export default function Login({ onSignedIn }: { onSignedIn: () => void }) {
  const [candidates, setCandidates] = useState<Candidate[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchCandidates()
      .then(setCandidates)
      .catch((e) => setError(String(e.message ?? e)));
  }, []);

  function pick(c: Candidate) {
    setPatientId(c.fin);
    onSignedIn();
  }

  return (
    <div className="login">
      <div className="brand">
        <h1>My Recovery</h1>
        <p>Memorial General · hip &amp; femur fracture program</p>
      </div>

      <div className="synthetic-banner" style={{ borderRadius: 8, marginBottom: 22 }}>
        Synthetic demo data — not real patients
      </div>

      <h2 style={{ fontSize: 17, marginBottom: 4 }}>Who's signing in?</h2>
      <p style={{ color: "var(--muted)", fontSize: 15, marginBottom: 16 }}>
        Choose your name. A caregiver can use the same sign-in.
      </p>

      {error && <ErrorNote error={error} />}
      {!candidates && !error && <Loading what="patients" />}

      {candidates?.map((c) => (
        <button key={c.fin} type="button" className="patient-pick" onClick={() => pick(c)}>
          <div className="pname">{c.patient_name}</div>
          <div className="pmeta">
            {c.age != null ? `${c.age} years old · ` : ""}
            home {shortDate(c.discharge_date)}
            {c.disposition ? ` · ${c.disposition}` : ""}
            {c.enrolled ? " · already set up" : ""}
          </div>
        </button>
      ))}

      {candidates?.length === 0 && (
        <div className="empty">
          No active recovery episodes at the current demo date.
        </div>
      )}
    </div>
  );
}
