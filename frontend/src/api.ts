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
  /** Patient-app engagement (additive fields; false/null when not enrolled). */
  enrolled: boolean;
  last_checkin_date: string | null;
  checkin_adherence: number | null;
  open_redflags: number;
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

// ---------------------------------------------------------------------------
// Patient-app data (companion app writes; see patient/ and
// backend/app/routers/patient_signals.py)
// ---------------------------------------------------------------------------

export interface PatientSignal {
  id: number;
  occurred_at: string;
  kind: string;
  label: string;
  severity: string | null;
  detail: Record<string, unknown>;
  headline: string;
}

export interface SignalsResponse {
  meta: {
    as_of: string;
    as_of_mode: "frozen" | "live";
    fin: string;
    patient_id: number;
    patient_name: string;
    total: number;
  };
  signals: PatientSignal[];
  counts: Record<string, number>;
}

export interface AdherenceBlock {
  checkin: { days_completed: number; days_expected: number; pct: number | null };
  pt: {
    days_logged: number;
    days_expected: number;
    sessions_logged: number;
    pct: number | null;
  };
  medication: {
    taken: number;
    missed: number;
    pct: number | null;
    anticoagulant_taken: number;
    anticoagulant_missed: number;
    anticoagulant_pct: number | null;
  };
}

export interface PatientMilestone {
  code: string;
  phase: string;
  label: string;
  target_date: string | null;
  status: "pending" | "met" | "missed";
  met_at: string | null;
}

export interface PatientChecklist {
  checklist_code: string;
  title: string;
  answered: number;
  total: number;
  blockers: { item_code: string; label: string; note: string | null }[];
  last_answered_at: string | null;
}

export interface PatientRedFlag {
  id: number;
  category: string;
  severity: string;
  guidance_code: string | null;
  reported_at: string;
  reasons: string[];
  queue_item_id: number | null;
}

export interface PatientSummaryResponse {
  meta: { as_of: string; fin: string; patient_name: string };
  enrolled: boolean;
  enrollment: {
    relationship: string;
    confirmed_procedure_type: string | null;
    confirmed_surgeon: string | null;
    confirmed_discharge_destination: string | null;
    enrolled_at: string;
  } | null;
  phase: string | null;
  phase_label: string | null;
  milestones: PatientMilestone[];
  adherence: AdherenceBlock;
  latest_checkin: {
    checkin_date: string;
    pain_score: number | null;
    mood: string | null;
    sleep_quality: string | null;
    mobility_status: string | null;
    weight_bearing_status: string | null;
    pt_completed: number | null;
  } | null;
  checkin_trend: {
    checkin_date: string;
    pain_score: number | null;
    mobility_status: string | null;
    pt_completed: number | null;
    weight_bearing_status: string | null;
    mood: string | null;
  }[];
  red_flags: PatientRedFlag[];
  checklists: PatientChecklist[];
  open_alerts: number;
}

export async function fetchPatientSignals(fin: string): Promise<SignalsResponse> {
  const res = await fetch(`/api/episodes/${encodeURIComponent(fin)}/signals`);
  if (!res.ok) throw new Error(`signals request failed: ${res.status}`);
  return res.json();
}

export async function fetchPatientSummary(fin: string): Promise<PatientSummaryResponse> {
  const res = await fetch(`/api/episodes/${encodeURIComponent(fin)}/patient-summary`);
  if (!res.ok) throw new Error(`patient summary request failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Care-team messaging (provider side)
// ---------------------------------------------------------------------------

export interface CareMessage {
  id: number;
  sender_role: string;
  sender_name: string | null;
  body: string;
  sent_at: string;
  read_at: string | null;
}

export interface CareThread {
  id: number;
  patient_id: number;
  patient_name: string | null;
  fin: string;
  subject: string;
  status: string;
  last_message_at: string | null;
  unread_provider: number;
  message_count: number;
  last_preview: string | null;
  messages: CareMessage[];
}

export interface InboxResponse {
  meta: { status: string; total: number; unread_threads: number };
  threads: CareThread[];
}

export async function fetchInbox(status = "open"): Promise<InboxResponse> {
  const res = await fetch(`/api/messages?status=${encodeURIComponent(status)}`);
  if (!res.ok) throw new Error(`inbox request failed: ${res.status}`);
  return res.json();
}

export async function replyToThread(threadId: number, body: string): Promise<unknown> {
  const res = await fetch(`/api/messages/${threadId}/reply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body }),
  });
  if (!res.ok) throw new Error(`reply failed: ${res.status}`);
  return res.json();
}

export async function closeThread(threadId: number): Promise<unknown> {
  const res = await fetch(`/api/messages/${threadId}/close`, { method: "POST" });
  if (!res.ok) throw new Error(`close failed: ${res.status}`);
  return res.json();
}

/**
 * Assign a queue item to a role. The endpoint existed from M6 but had no client
 * function, so the UI could never call it.
 */
export async function assignQueueItem(id: number, role: string): Promise<QueueItem> {
  const res = await fetch(`/api/queue/${id}/assign`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role }),
  });
  if (!res.ok) throw new Error(`assign failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Executive view (D13 / D15) — episode economics by post-acute destination
// ---------------------------------------------------------------------------

/** Shared caveats every exec response carries; the UI renders them, not hides them. */
export interface ExecMeta {
  as_of: string;
  as_of_mode: "frozen" | "live";
  org_name: string;
  episodes: number;
  closed_episodes: number;
  in_flight_episodes: number;
  min_n_for_delta: number;
  basis: string;
  window_days: number;
  claims_lag_note: string;
}

export interface ExecKpis {
  episodes: number;
  closed_episodes: number;
  in_flight_episodes: number;
  total_spend: number;
  spend_to_date: number;
  avg_spend_closed: number | null;
  avg_target_closed: number | null;
  /** Positive = under target across closed episodes. */
  net_savings_closed: number | null;
  savings_rate_closed: number | null;
  episodes_over_target: number;
  avg_ip_los: number | null;
  readmit_rate_closed: number | null;
  pct_discharged_home: number | null;
  post_acute_share: number | null;
}

export interface ExecOpportunity {
  facility_key: string;
  facility_name: string;
  setting_label: string;
  episodes: number;
  post_acute_days: number;
  cost_per_day: number;
  peer_cost_per_day: number;
  price_ratio: number;
  avoidable_spend: number;
  avoidable_per_episode: number;
  headline: string;
  action: string;
}

export interface ExecSummaryResponse {
  meta: ExecMeta;
  kpis: ExecKpis;
  opportunity: ExecOpportunity | null;
}

export interface FacilityRow {
  facility_key: string;
  facility_name: string;
  setting: string;
  setting_label: string;
  ownership: string;
  episodes: number;
  closed_episodes: number;
  total_spend: number;
  avg_spend: number | null;
  avg_target: number | null;
  /** Positive = over target. Null until the facility has enough closed episodes. */
  avg_variance: number | null;
  post_acute_spend: number;
  post_acute_days: number;
  cost_per_post_acute_day: number | null;
  peer_cost_per_day: number | null;
  price_ratio: number | null;
  avg_ip_los: number | null;
  readmit_rate: number | null;
  delta_suppressed: boolean;
  is_price_outlier: boolean;
}

export interface CostDriver {
  category: string;
  label: string;
  amount: number;
  excess: number;
  share: number;
}

export interface EpisodeCostRow {
  fin: string;
  patient_id: number;
  mrn: string;
  patient_name: string;
  age: number | null;
  ms_drg: string | null;
  discharge_date: string | null;
  window_end: string | null;
  status: "closed" | "in_flight" | "predischarge" | "unknown";
  setting: string;
  facility_key: string;
  facility_name: string;
  comorbidity_count: number | null;
  length_of_stay_days: number | null;
  post_acute_days: number | null;
  target_price: number | null;
  actual_spend: number;
  /** Closed episodes only — a partial episode has no meaningful variance. */
  variance: number | null;
  variance_pct: number | null;
  target_consumed_pct: number | null;
  peer_median: number | null;
  is_outlier: boolean;
  had_readmission: boolean;
  drivers: CostDriver[];
}

export interface FacilityListResponse {
  meta: ExecMeta;
  facilities: FacilityRow[];
}

export interface FacilityDetailResponse {
  meta: ExecMeta;
  facility: FacilityRow;
  episodes: EpisodeCostRow[];
}

export interface OutlierResponse {
  meta: ExecMeta;
  episodes: EpisodeCostRow[];
}

export interface CostCategoryRow {
  category: string;
  label: string;
  cohort_per_episode: number;
  selected_per_episode: number;
}

export interface CostCategoryResponse {
  meta: ExecMeta;
  selected_key: string;
  selected_label: string;
  categories: CostCategoryRow[];
}

export async function fetchExecSummary(): Promise<ExecSummaryResponse> {
  const res = await fetch("/api/exec/summary");
  if (!res.ok) throw new Error(`exec summary failed: ${res.status}`);
  return res.json();
}

export async function fetchFacilities(): Promise<FacilityListResponse> {
  const res = await fetch("/api/exec/facilities");
  if (!res.ok) throw new Error(`facilities request failed: ${res.status}`);
  return res.json();
}

export async function fetchFacilityEpisodes(
  facilityKey: string,
): Promise<FacilityDetailResponse> {
  const res = await fetch(
    `/api/exec/facilities/${encodeURIComponent(facilityKey)}/episodes`,
  );
  if (!res.ok) throw new Error(`facility drill-down failed: ${res.status}`);
  return res.json();
}

export async function fetchOutliers(limit = 8): Promise<OutlierResponse> {
  const res = await fetch(`/api/exec/outliers?limit=${limit}`);
  if (!res.ok) throw new Error(`outliers request failed: ${res.status}`);
  return res.json();
}

export async function fetchCostCategories(
  facilityKey?: string,
): Promise<CostCategoryResponse> {
  const qs = facilityKey ? `?facility=${encodeURIComponent(facilityKey)}` : "";
  const res = await fetch(`/api/exec/cost-categories${qs}`);
  if (!res.ok) throw new Error(`cost categories failed: ${res.status}`);
  return res.json();
}
