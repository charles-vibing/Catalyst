/**
 * Onboarding / enrollment (A1).
 *
 * A confirmation flow, not a data-entry form: the hospital record already knows
 * the procedure, surgeon, and discharge destination, so the patient verifies
 * what we have. Anything they change is stored as the *confirmed* value
 * alongside the EHR value, so a mismatch stays visible to the navigator rather
 * than silently overwriting the chart.
 *
 * Four short steps, because a 12-field form is where an 80-year-old on a phone
 * gives up.
 */

import { useState } from "react";
import { MeResponse, submitEnrollment } from "./api";
import { Choices, ErrorNote, Field, friendlyDate, prettify } from "./components/ui";

const RELATIONSHIP_LABELS: Record<string, string> = {
  self: "I'm the patient",
  caregiver: "I'm a family member or caregiver",
};

const STEPS = 4;

export default function Onboarding({
  me,
  onDone,
}: {
  me: MeResponse;
  onDone: () => void;
}) {
  const o = me.onboarding;
  const [step, setStep] = useState(0);
  const [relationship, setRelationship] = useState(o.relationship_options[0] ?? "self");
  const [procedureType, setProcedureType] = useState(o.procedure_type_suggested);
  const [surgeon, setSurgeon] = useState(o.surgeon_suggested ?? "");
  const [destination, setDestination] = useState(o.destination_suggested ?? "");
  const [phone, setPhone] = useState(o.contact_phone_suggested ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function finish() {
    setSaving(true);
    setError(null);
    try {
      await submitEnrollment({
        relationship,
        confirmed_procedure_type: procedureType,
        confirmed_procedure_text: o.procedure_text_suggested,
        confirmed_surgeon: surgeon || null,
        confirmed_discharge_destination: destination || null,
        contact_phone: phone || null,
      });
      onDone();
    } catch (e) {
      setError(String((e as Error).message ?? e));
      setSaving(false);
    }
  }

  return (
    <div className="screen">
      <div className="steps">
        {Array.from({ length: STEPS }, (_, i) => (
          <div key={i} className={i <= step ? "dot on" : "dot"} />
        ))}
      </div>

      {error && <ErrorNote error={error} />}

      {step === 0 && (
        <>
          <h2>Welcome, {me.episode.patient_name.split(",")[1]?.trim() ?? "there"}</h2>
          <p className="lede">
            This app helps you through the weeks after your surgery at{" "}
            {me.episode.hospital}. Your care team sees what you enter here.
          </p>
          <Field label="First, who's using the app?">
            <Choices
              options={o.relationship_options}
              labels={RELATIONSHIP_LABELS}
              value={relationship}
              onChange={setRelationship}
              stacked
            />
          </Field>
          <button type="button" className="btn primary block" onClick={() => setStep(1)}>
            Continue
          </button>
        </>
      )}

      {step === 1 && (
        <>
          <h2>Let's check your surgery</h2>
          <p className="lede">This is what the hospital has on record.</p>

          <div className="card tinted">
            <h3>{prettify(procedureType)} surgery</h3>
            <div className="sub">{o.procedure_text_suggested}</div>
            {me.episode.procedure_date && (
              <div className="sub" style={{ marginTop: 8 }}>
                {friendlyDate(me.episode.procedure_date)}
              </div>
            )}
          </div>

          <Field
            label="Is that right?"
            hint="If this doesn't look right, pick the other one and we'll tell your team."
          >
            <Choices
              options={o.procedure_type_options}
              labels={{ hip: "Hip surgery", femur: "Thigh bone (femur) surgery" }}
              value={procedureType}
              onChange={setProcedureType}
              stacked
            />
          </Field>

          <div className="btn-row">
            <button type="button" className="btn" onClick={() => setStep(0)}>
              Back
            </button>
            <button
              type="button"
              className="btn primary"
              style={{ flex: 1 }}
              onClick={() => setStep(2)}
            >
              Continue
            </button>
          </div>
        </>
      )}

      {step === 2 && (
        <>
          <h2>Your surgeon</h2>
          <p className="lede">The doctor who did your operation.</p>
          <Field label="Surgeon">
            <input
              type="text"
              value={surgeon}
              onChange={(e) => setSurgeon(e.target.value)}
              placeholder="Surgeon's name"
            />
          </Field>
          <Field label="Best phone number for you" hint="Only used by your care team.">
            <input
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="Phone number"
            />
          </Field>
          <div className="btn-row">
            <button type="button" className="btn" onClick={() => setStep(1)}>
              Back
            </button>
            <button
              type="button"
              className="btn primary"
              style={{ flex: 1 }}
              onClick={() => setStep(3)}
            >
              Continue
            </button>
          </div>
        </>
      )}

      {step === 3 && (
        <>
          <h2>Where you're recovering</h2>
          <p className="lede">
            The hospital recorded that you went to:{" "}
            <strong>{o.destination_suggested}</strong>
          </p>
          <Field label="Where are you now?">
            <Choices
              options={o.destination_options}
              value={destination}
              onChange={setDestination}
              stacked
            />
          </Field>
          <div className="btn-row">
            <button type="button" className="btn" onClick={() => setStep(2)}>
              Back
            </button>
            <button
              type="button"
              className="btn primary"
              style={{ flex: 1 }}
              disabled={saving}
              onClick={finish}
            >
              {saving ? "Setting up…" : "Finish setup"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
