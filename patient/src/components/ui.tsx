/**
 * Small shared presentational pieces for the patient app.
 *
 * Deliberately plain — no component library, matching the dashboard's approach
 * of composing semantic elements with hand-written CSS classes.
 */

import { ReactNode } from "react";

export function Card({
  title,
  children,
  tinted,
}: {
  title?: string;
  children: ReactNode;
  tinted?: boolean;
}) {
  return (
    <div className={tinted ? "card tinted" : "card"}>
      {title && <h3>{title}</h3>}
      {children}
    </div>
  );
}

export function Loading({ what = "…" }: { what?: string }) {
  return <div className="loading">Loading {what}</div>;
}

export function ErrorNote({ error }: { error: string }) {
  return <div className="notice error">{error}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

/** 0–10 pain-style scale. */
export function Scale({
  value,
  min = 0,
  max = 10,
  lowLabel,
  highLabel,
  onChange,
}: {
  value: number | null;
  min?: number;
  max?: number;
  lowLabel?: string;
  highLabel?: string;
  onChange: (v: number) => void;
}) {
  const steps = [];
  for (let i = min; i <= max; i++) steps.push(i);
  return (
    <>
      <div className="scale">
        {steps.map((n) => (
          <button
            key={n}
            type="button"
            className={value === n ? "selected" : undefined}
            aria-pressed={value === n}
            onClick={() => onChange(n)}
          >
            {n}
          </button>
        ))}
      </div>
      {(lowLabel || highLabel) && (
        <div className="scale-ends">
          <span>{lowLabel}</span>
          <span>{highLabel}</span>
        </div>
      )}
    </>
  );
}

export function Choices({
  options,
  labels,
  value,
  onChange,
  stacked,
}: {
  options: string[];
  labels?: Record<string, string>;
  value: string | null;
  onChange: (v: string) => void;
  stacked?: boolean;
}) {
  return (
    <div className={stacked ? "choices stacked" : "choices"}>
      {options.map((opt) => (
        <button
          key={opt}
          type="button"
          className={value === opt ? "choice selected" : "choice"}
          aria-pressed={value === opt}
          onClick={() => onChange(opt)}
        >
          {labels?.[opt] ?? prettify(opt)}
        </button>
      ))}
    </div>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string | null;
  children: ReactNode;
}) {
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      {hint && <div className="hint">{hint}</div>}
      {children}
    </div>
  );
}

export function Stat({ value, label }: { value: ReactNode; label: string }) {
  return (
    <div className="stat">
      <div className="value">{value}</div>
      <div className="label">{label}</div>
    </div>
  );
}

/** Guidance panel for red-flag results — colour keyed to urgency. */
export function GuidanceBox({
  headline,
  body,
  urgency,
  contact,
}: {
  headline: string;
  body: string;
  urgency: string;
  contact?: { name: string | null; relationship: string | null; phone: string | null } | null;
}) {
  return (
    <div className={`guidance ${urgency}`}>
      <h3>{headline}</h3>
      <p>{body}</p>
      {contact?.name && (
        <div className="contact">
          Your emergency contact: <strong>{contact.name}</strong>
          {contact.relationship ? ` (${contact.relationship})` : ""}
          {contact.phone ? ` — ${contact.phone}` : ""}
        </div>
      )}
    </div>
  );
}

export function prettify(value: string): string {
  const words = value.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** "Saturday 21 June" — patient-facing dates never show ISO strings. */
export function friendlyDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso.length <= 10 ? `${iso}T12:00:00` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
}

export function shortDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso.length <= 10 ? `${iso}T12:00:00` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export function timeOf(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}
