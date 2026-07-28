/**
 * Patient companion app API client.
 *
 * Mirrors the dashboard's frontend/src/api.ts: bare fetch, explicit interfaces,
 * no data-fetching library. Every request carries the X-Catalyst-Patient header
 * — the demo stand-in for a login (see backend/app/auth.py). Per
 * design/security-foundations.md §5 only that identifier is persisted in the
 * browser, never chart data.
 */

const PATIENT_KEY = "catalyst.patient";

/**
 * Resolve the acting patient: `?patient=<FIN|MRN|id>` wins over localStorage
 * and is persisted, so a demo link like /?patient=007521 drops straight into
 * that episode. Only this identifier is stored in the browser — never chart
 * data (design/security-foundations.md §5).
 */
export function getPatientId(): string | null {
  const fromUrl = new URLSearchParams(window.location.search).get("patient");
  if (fromUrl) {
    localStorage.setItem(PATIENT_KEY, fromUrl);
    return fromUrl;
  }
  return localStorage.getItem(PATIENT_KEY);
}

export function setPatientId(id: string): void {
  localStorage.setItem(PATIENT_KEY, id);
}

export function clearPatientId(): void {
  localStorage.removeItem(PATIENT_KEY);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const patient = getPatientId();
  const res = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(patient ? { "X-Catalyst-Patient": patient } : {}),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : detail;
    } catch {
      /* non-JSON error body */
    }
    const err = new Error(detail) as Error & { status?: number };
    err.status = res.status;
    throw err;
  }
  return res.json();
}

function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) });
}

// ---------------------------------------------------------------------------
// Identity + enrollment
// ---------------------------------------------------------------------------

export interface Candidate {
  patient_id: number;
  fin: string;
  mrn: string;
  patient_name: string;
  age: number | null;
  discharge_date: string | null;
  disposition: string | null;
  procedure_summary: string | null;
  enrolled: boolean;
}

export interface EpisodeSummary {
  fin: string;
  mrn: string;
  patient_name: string;
  procedure_text: string | null;
  procedure_type: string;
  procedure_date: string | null;
  surgeon: string | null;
  admit_date: string | null;
  discharge_date: string | null;
  window_end: string | null;
  disposition: string | null;
  disposition_code: string | null;
  hospital: string;
}

export interface Enrollment {
  relationship: string;
  confirmed_procedure_type: string | null;
  confirmed_procedure_text: string | null;
  confirmed_surgeon: string | null;
  confirmed_discharge_destination: string | null;
  contact_phone: string | null;
  enrolled_at: string;
  status: string;
}

export interface MeResponse {
  meta: { as_of: string; as_of_mode: string; org_name: string; days_remaining: number | null };
  episode: EpisodeSummary;
  phase: string;
  phase_label: string;
  enrolled: boolean;
  enrollment: Enrollment | null;
  onboarding: {
    procedure_type_options: string[];
    procedure_type_suggested: string;
    procedure_text_suggested: string | null;
    surgeon_suggested: string | null;
    destination_suggested: string | null;
    destination_options: string[];
    relationship_options: string[];
    contact_phone_suggested: string | null;
  };
}

export const fetchCandidates = () => request<Candidate[]>("/api/patient/candidates");
export const fetchMe = () => request<MeResponse>("/api/patient/me");
export const submitEnrollment = (body: Record<string, unknown>) =>
  post<Enrollment>("/api/patient/enrollment", body);

// ---------------------------------------------------------------------------
// Timeline
// ---------------------------------------------------------------------------

export interface Milestone {
  code: string;
  phase: string;
  label: string;
  target_date: string | null;
  status: "pending" | "met" | "missed";
  met_at: string | null;
}

export interface PhaseProgress {
  phase: string;
  label: string;
  state: "done" | "current" | "upcoming";
  milestones_total: number;
  milestones_met: number;
}

export interface TimelineResponse {
  meta: { as_of: string; days_remaining: number | null; window_end: string | null };
  headline: string;
  subhead: string;
  phase: string;
  phase_label: string;
  phases: PhaseProgress[];
  milestones: Milestone[];
  next_milestone: Milestone | null;
  progress: {
    milestones_met: number;
    milestones_total: number;
    milestones_missed: number;
    checkin: { days_completed: number; days_expected: number; pct: number | null };
    pt: { days_logged: number; days_expected: number; sessions_logged: number; pct: number | null };
    medication: {
      taken: number;
      missed: number;
      pct: number | null;
      anticoagulant_pct: number | null;
    };
  };
}

export const fetchTimeline = () => request<TimelineResponse>("/api/patient/timeline");

// ---------------------------------------------------------------------------
// Daily check-in
// ---------------------------------------------------------------------------

export interface Checkin {
  checkin_date: string;
  pain_score: number | null;
  mood: string | null;
  sleep_quality: string | null;
  mobility_status: string | null;
  weight_bearing_status: string | null;
  pt_completed: boolean | null;
  note: string | null;
  submitted_at: string | null;
}

export interface CheckinField {
  type: string;
  label: string;
  options?: string[];
  labels?: Record<string, string>;
  min?: number;
  max?: number;
  order_text?: string | null;
}

export interface TodayResponse {
  meta: { as_of: string; phase: string };
  already_submitted: boolean;
  checkin: Checkin | null;
  form: Record<string, CheckinField>;
  streak_days: number;
}

export interface CheckinSubmitResponse {
  checkin: Checkin;
  acknowledgement: string;
  alerts: { queue_item_id: number; severity: string; concerns: string[] }[];
  milestones_met: string[];
}

export const fetchToday = () => request<TodayResponse>("/api/patient/checkin/today");
export const fetchCheckinHistory = (days = 14) =>
  request<Checkin[]>(`/api/patient/checkin/history?days=${days}`);
export const submitCheckin = (body: Record<string, unknown>) =>
  post<CheckinSubmitResponse>("/api/patient/checkin", body);

// ---------------------------------------------------------------------------
// Red flags
// ---------------------------------------------------------------------------

export interface RedFlagQuestion {
  key: string;
  type: "bool" | "scale" | "choice";
  label: string;
  options?: string[];
  min?: number;
  max?: number;
  step?: number;
  optional?: boolean;
}

export interface RedFlagCategory {
  category: string;
  title: string;
  prompt: string;
  questions: RedFlagQuestion[];
}

export interface Guidance {
  headline: string;
  body: string;
  urgency: string;
}

export interface RedFlagQuestionsResponse {
  categories: RedFlagCategory[];
  guidance: Record<string, Guidance>;
}

export interface RedFlagReport {
  id: number;
  category: string;
  title: string;
  severity: string;
  guidance_code: string | null;
  reasons: string[];
  reported_at: string;
  queue_item_id: number | null;
}

export interface RedFlagSubmitResponse {
  report: RedFlagReport;
  guidance: Guidance;
  care_team_notified: boolean;
  emergency_contact: { name: string | null; relationship: string | null; phone: string | null } | null;
}

export const fetchRedFlagQuestions = () =>
  request<RedFlagQuestionsResponse>("/api/patient/redflags/questions");
export const fetchRedFlags = () => request<RedFlagReport[]>("/api/patient/redflags");
export const submitRedFlag = (category: string, answers: Record<string, unknown>) =>
  post<RedFlagSubmitResponse>("/api/patient/redflags", { category, answers });

// ---------------------------------------------------------------------------
// Exercises
// ---------------------------------------------------------------------------

export interface Exercise {
  code: string;
  phase: string;
  name: string;
  description: string | null;
  video_url: string | null;
  default_sets: number | null;
  default_reps: number | null;
  weight_bearing_note: string | null;
  logged_today: boolean;
  sets_done: number | null;
  reps_done: number | null;
  difficulty: string | null;
}

export interface ExerciseListResponse {
  phase: string;
  prescription: {
    weight_bearing: string | null;
    therapist: string | null;
    goals: string[];
    equipment: string[];
  };
  exercises: Exercise[];
  adherence: { days_logged: number; days_expected: number; sessions_logged: number; pct: number | null };
}

export const fetchExercises = () => request<ExerciseListResponse>("/api/patient/exercises");
export const logExercise = (body: Record<string, unknown>) =>
  post<{ adherence: ExerciseListResponse["adherence"]; acknowledgement: string; milestones_met: string[] }>(
    "/api/patient/exercises/log",
    body,
  );

// ---------------------------------------------------------------------------
// Medications
// ---------------------------------------------------------------------------

export interface DoseSlot {
  dose_index: number;
  reminder_time: string | null;
  status: string | null;
  recorded_at: string | null;
}

export interface Medication {
  id: number;
  name_display: string;
  med_class: string;
  sig: string | null;
  frequency_per_day: number;
  reminder_time: string | null;
  indication: string | null;
  doses_today: DoseSlot[];
}

export interface MedListResponse {
  medications: Medication[];
  adherence: {
    taken: number;
    missed: number;
    pct: number | null;
    anticoagulant_taken: number;
    anticoagulant_missed: number;
    anticoagulant_pct: number | null;
  };
  anticoagulant_names: string[];
}

export const fetchMedications = () => request<MedListResponse>("/api/patient/medications");
export const recordDose = (body: Record<string, unknown>) =>
  post<{ adherence: MedListResponse["adherence"]; acknowledgement: string; alerts: unknown[] }>(
    "/api/patient/medications/dose",
    body,
  );

// ---------------------------------------------------------------------------
// Appointments
// ---------------------------------------------------------------------------

export interface Appointment {
  id: number;
  kind: string;
  title: string;
  provider_name: string | null;
  scheduled_at: string | null;
  location: string | null;
  confirmed: boolean;
  attended: boolean | null;
  source: string;
  is_past: boolean;
  due_soon: boolean;
}

export interface AppointmentListResponse {
  upcoming: Appointment[];
  past: Appointment[];
  needs_attendance_answer: Appointment[];
}

export const fetchAppointments = () =>
  request<AppointmentListResponse>("/api/patient/appointments");
export const confirmAppointment = (id: number) =>
  post<Appointment>(`/api/patient/appointments/${id}/confirm`);
export const recordAttendance = (id: number, attended: boolean) =>
  post<Appointment>(`/api/patient/appointments/${id}/attended`, { attended });

// ---------------------------------------------------------------------------
// Messages
// ---------------------------------------------------------------------------

export interface Message {
  id: number;
  sender_role: string;
  sender_name: string | null;
  body: string;
  sent_at: string;
  read_at: string | null;
}

export interface Thread {
  id: number;
  subject: string;
  status: string;
  created_at: string;
  last_message_at: string | null;
  unread_patient: number;
  messages: Message[];
}

export interface ThreadListResponse {
  meta: { unread_total: number };
  threads: Thread[];
  care_team: { role: string; name: string }[];
}

export const fetchThreads = () => request<ThreadListResponse>("/api/patient/messages");
export const sendMessage = (body: Record<string, unknown>) =>
  post<{ thread_id: number; acknowledgement: string; care_team_notified: boolean }>(
    "/api/patient/messages",
    body,
  );
export const markThreadRead = (id: number) => post(`/api/patient/messages/${id}/read`);

// ---------------------------------------------------------------------------
// Checklists
// ---------------------------------------------------------------------------

export interface ChecklistItem {
  item_code: string;
  label: string;
  help_text: string | null;
  critical: boolean;
  answer: string | null;
  note: string | null;
  answered_at: string | null;
}

export interface ChecklistProgress {
  answered: number;
  total: number;
  pct: number | null;
  critical_total: number;
  critical_cleared: number;
  blockers: string[];
  complete: boolean;
}

export interface ChecklistResponse {
  checklist_code: string;
  title: string;
  intro: string;
  phase: string;
  unlocked: boolean;
  items: ChecklistItem[];
  progress: ChecklistProgress;
}

export interface AvailableChecklists {
  phase: string;
  available: {
    checklist_code: string;
    title: string;
    intro: string | null;
    progress: ChecklistProgress;
  }[];
}

export const fetchChecklists = () => request<AvailableChecklists>("/api/patient/checklists");
export const fetchChecklist = (code: string) =>
  request<ChecklistResponse>(`/api/patient/checklist/${code}`);
export const saveChecklist = (
  code: string,
  answers: { item_code: string; answer: string; note?: string }[],
) =>
  post<{
    progress: ChecklistProgress;
    acknowledgement: string;
    flagged_items: string[];
    milestones_met: string[];
  }>(`/api/patient/checklist/${code}`, { answers });
