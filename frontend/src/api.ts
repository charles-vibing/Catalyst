export type EpisodeStatus = "upcoming" | "active" | "completed";

export interface Episode {
  patient_id: number;
  mrn: string;
  patient_name: string;
  age: number | null;
  sex: string | null;
  fin: string;
  admit_date: string | null;
  discharge_date: string | null;
  window_end: string | null;
  ms_drg: string | null;
  procedure_summary: string | null;
  procedure_date: string | null;
  disposition: string | null;
  disposition_code: string | null;
  status: EpisodeStatus;
  days_remaining: number | null;
}

export interface RosterMeta {
  as_of: string;
  as_of_mode: "frozen" | "live";
  org_id: string;
  org_name: string;
  total: number;
  status_counts: Partial<Record<EpisodeStatus, number>>;
}

export interface RosterResponse {
  meta: RosterMeta;
  episodes: Episode[];
}

export interface EpisodeHeader extends Episode {
  admit_datetime: string | null;
  discharge_datetime: string | null;
  principal_diagnosis: string | null;
  attending_name: string | null;
  length_of_stay_days: number | null;
}

export interface Problem {
  description: string;
  icd10: string | null;
  status: string | null;
}

export interface DischargeMed {
  name: string;
  sig: string | null;
  route: string | null;
  frequency: string | null;
  indication: string | null;
}

export interface LabResult {
  display: string;
  value: string | null;
  unit: string | null;
  abnormal_flag: string | null;
  effective_at: string | null;
}

export interface DischargeVitals {
  recorded_at: string | null;
  temp_f: number | null;
  heart_rate: number | null;
  resp_rate: number | null;
  bp_systolic: number | null;
  bp_diastolic: number | null;
  spo2_percent: number | null;
  o2_delivery: string | null;
  pain_score: number | null;
}

export interface TherapyInfo {
  weight_bearing: string | null;
  recommendation: string | null;
  equipment: string[];
  eval_date: string | null;
}

export interface CareTeamMember {
  role: string;
  name: string;
}

export interface DispositionContext {
  code: string | null;
  label: string | null;
  title: string;
  bullets: string[];
  emergency_contact: {
    name: string | null;
    relationship: string | null;
    phone: string | null;
  };
}

export interface PcpInfo {
  status: string | null;
  referred_to: string | null;
  appointment_datetime: string | null;
  ordered_at: string | null;
  gap: boolean;
  note: string | null;
}

export interface TimelineEvent {
  at: string | null;
  kind: string;
  label: string;
  detail: string | null;
}

export interface ClinicalDocument {
  document_type: string;
  service_date: string | null;
  author: string | null;
  file_name: string | null;
}

export interface EpisodeDetailResponse {
  meta: {
    as_of: string;
    as_of_mode: "frozen" | "live";
    org_id: string;
    org_name: string;
  };
  episode: EpisodeHeader;
  problems: Problem[];
  discharge_meds: DischargeMed[];
  labs: LabResult[];
  discharge_vitals: DischargeVitals | null;
  therapy: TherapyInfo | null;
  care_team: CareTeamMember[];
  disposition_context: DispositionContext;
  pcp: PcpInfo | null;
  timeline: TimelineEvent[];
  documents: ClinicalDocument[];
}

export async function fetchRoster(): Promise<RosterResponse> {
  const res = await fetch("/api/roster");
  if (!res.ok) {
    throw new Error(`roster request failed: ${res.status}`);
  }
  return res.json();
}

export async function fetchEpisode(fin: string): Promise<EpisodeDetailResponse> {
  const res = await fetch(`/api/episodes/${encodeURIComponent(fin)}`);
  if (!res.ok) {
    throw new Error(`episode request failed: ${res.status}`);
  }
  return res.json();
}

export type QueueSeverity = "red" | "yellow";
export type ResolveAction = "call_caregiver" | "call_patient" | "mark_resolved";

export interface QueueItem {
  id: number;
  kind: string;
  severity: QueueSeverity | string;
  title: string;
  summary: string | null;
  patient_id: number;
  patient_name: string | null;
  fin: string | null;
  priority: number | null;
  assigned_role: string | null;
  status: string;
  created_at: string | null;
  resolution_action?: string | null;
  resolution_note?: string | null;
  resolved_at?: string | null;
}

export interface QueueListResponse {
  items: QueueItem[];
  meta: { org_id: string; status: string; total: number };
}

export async function fetchQueue(status = "open"): Promise<QueueListResponse> {
  const res = await fetch(`/api/queue?status=${encodeURIComponent(status)}`);
  if (!res.ok) {
    throw new Error(`queue request failed: ${res.status}`);
  }
  return res.json();
}

export async function resolveQueueItem(
  id: number,
  action: ResolveAction,
  note?: string,
): Promise<QueueItem> {
  const res = await fetch(`/api/queue/${id}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, note: note ?? null }),
  });
  if (!res.ok) {
    throw new Error(`resolve failed: ${res.status}`);
  }
  return res.json();
}
