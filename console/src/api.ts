// Typed reads from the RUKO risk engine (contract C5). Same origin: the engine serves the built
// console at /console/, and `npm run dev` proxies /v1, /health and /sim to it.

export type Tier = "T0" | "T1" | "T2" | "T3" | "T4";

export interface Health {
  status: string;
  model_version: string;
  policy_version: string;
  contract_version: string;
  demo_clock: boolean;
}

export interface Alert {
  alert_id: string;
  payment_id?: string;
  ts: string;
  user_hash: string;
  payee: string;
  amount_inr: number;
  tier: Tier;
  reasons: string[];
  message_key: string | null;
  playbook: string | null;
  stage: string;
  pause_minutes: number;
  stage_path: [string, string][];
  families: string[];
  evidence_id: string | null;
  entry_method: string;
}

export interface EpisodeCase {
  case_id: string;
  opened_at: string;
  user_hash: string;
  episode_id: string;
  evidence_id: string;
  accounts: string[];
  reasons: string[];
  loop_paths: string[];
}

export interface Review {
  approved_by: string[];
  rejected_by: string[];
  approved: boolean;
}

export interface Suspect {
  upi_id: string;
  band: "low" | "med" | "high";
  why: string;
  evidence_path: string[];
  ring_id: string | null;
  is_hub: boolean;
  first_seen: string | null;
  registry_listed: boolean;
  automated?: boolean;            // bot-scale: same amount to/from many people at a steady rhythm
  automation_why?: string | null;
  review: Review;
}

export interface Suspects {
  suspects: Suspect[];
  last_run: { ran_at: string; suspects: number; rings: number; error: string | null } | null;
  approvals_needed: number;
}

export interface Marks {
  flagged?: boolean;
  listed?: boolean;
  role?: string;
  verified_merchant?: boolean;
  holder_type?: string;
  name?: string;          // the account holder's name a bank SMS gave (c2-0.12)
}

export interface StoryNode {
  id: string;
  marks: Marks;
  users?: number;
  payments?: number;
  users_baited?: number;
  inr?: number;
  n?: number;
  hold_min?: number | null;
}

export interface StoryLink {
  from: string;
  to: string;
  kind: "bait" | "pay" | "forward" | "loop" | "shared";
  users?: number;
  n?: number;
  inr: number;
  hold_min?: number | null;
  completed?: number;
  completed_inr?: number;
}

export interface Story {
  center: string;
  center_role: "payee" | "bait_sender" | "account" | "unknown";
  known: boolean;
  senders: StoryNode[];
  users: { count: number; baited: number; paid: number };
  payees: StoryNode[];
  cashouts: StoryNode[];
  links: StoryLink[];
  loop: { found: boolean | null; path: string | null };
  flows_visible: boolean | null;
  signals: Record<string, unknown>;
  summary: string[];
}

/** One payment, traced by its id (the /v1/decide request_id) from the check to its outcome (c2-0.6). */
export interface Payment {
  payment_id: string;
  user: string;
  payee: string;
  inr: number;
  ts: string;
  checked: boolean;
  tier: Tier | null;
  reasons: string[];
  evidence_id: string | null;
  status: "checked" | "completed" | "cancelled";
  outcome_ts: string | null;
}

export interface PaymentList {
  account: string;
  total: number;
  by_status: Record<"checked" | "completed" | "cancelled", number>;
  completed_inr: number;
  payments: Payment[];
}

export interface Verify {
  ok: boolean;
  rows_checked: number;
  first_bad_id: string | null;
}

export interface Transaction {
  payment_id: string;
  user_hash: string;
  payee_upi: string;
  amount_inr: number;
  entry_method: string | null;
  ts: string;
  tier: Tier;
  reasons: string[];
  message_key: string | null;
  playbook: string | null;
  stage: string | null;
  scorer_version: string | null;
  policy_version: string | null;
  evidence_id: string | null;
  fail_open: boolean;
  latency_ms: number | null;
  status: "checked" | "completed" | "cancelled";
  outcome_ts: string | null;
}

/** Money a user received, read from a bank SMS on their phone (c2-0.11, opt-in). */
export interface Received {
  event_id: string;
  user_hash: string;
  sender_upi: string | null;
  amount_inr: number;
  ts: string;
  source: string;
  sender_name: string | null;   // c2-0.12: the name the bank SMS gave
}

export interface ExplainReason {
  code: string;
  text: string;
  family: string | null;
  strength: number | null;
  band: "small" | "medium" | "large" | null;
  signals: number;
  shown_to_user: boolean;
  inputs: Record<string, unknown>;
}

export interface DecisionSummary {
  headline: string;
  lit_needed: number;
  families: { family: string; name: string; score: number; lit: boolean; facts: string[] }[];
  how: string[];
  scam_type: string | null;
}

export interface Explanation {
  payment_id: string;
  summary: DecisionSummary;
  user_view: { tier: Tier; reasons: string[]; message_key: string | null; playbook: string | null; pause_minutes: number | null };
  scores: { p_scam: number | null; families: Record<string, number>; lit_families: string[]; family_names: Record<string, string> };
  reasons: ExplainReason[];
  playbooks: { playbook: string; rule: string; matched: boolean; chosen: boolean }[];
  policy_steps: string[];
  sources: Record<string, string>;
  stage_path: [string, string][];
  scorer_version: string | null;
  policy_version: string | null;
  evidence_id: string | null;
  fail_open: boolean;
}

export interface SpreadingHandle {
  kind: "upi" | "link" | "phone";
  value: string | null;          // the UPI ID; null for links and numbers (only their pseudonyms are known)
  users: number;
  spreading: boolean;
  first_seen: string;
  last_seen: string;
}

export interface Spreading {
  as_of: string;
  window_minutes: number;
  min_users: number;
  handles: SpreadingHandle[];
}

export interface AlertHealth {
  checks: number;
  tiers: Record<string, { shown: number; completed_share: number | null; cancelled_share: number | null; median_dwell_ms: number | null; actions: Record<string, number> }>;
  interruptions_per_1000_checks: number | null;
  actions: Record<string, number>;
  i_know_them: { accepted?: number; refused?: number };
  watch?: Record<string, number>;
  lures?: { lures_seen: number; ai_written: number };
}

export interface RingAccount {
  upi_id: string;
  role: "seed" | "suspect";
  why: string | null;
  band: "low" | "med" | "high" | null;
  is_hub: boolean;
  hub_score: number;
  hub_parts: Record<string, number>;
  payers: number;
  inr_in: number;
  inr_out: number;
  fastest_hold_min: number | null;
  automated: boolean;
  automation_why: string | null;
  registry_listed: boolean;
  approved: boolean;
  /** How a suspect is tied to the ring, in words (null for the accounts discovery started from). */
  linked_by: string | null;
}

export interface Ring {
  ring_id: string;
  size: number;
  accounts: RingAccount[];
  hubs: string[];
  victims: number;
  baited_users: number;
  money_from_victims_inr: number;
  fastest_hold_min: number | null;
  automated: boolean;
  links: { from: string; to: string; inr: number; n: number; hold_min: number | null; sources: string[] }[];
  victims_per_account: Record<string, number>;
  summary: string;
  explanation: { started_from: { upi_id: string; why: string }[]; linked_by: Record<string, string | null>; steps: string[] };
}

export interface EmergingPattern {
  pattern_id: string;
  description: string;
  summary: string;
  signature: Record<string, unknown>;
  payments: number;
  people: number;
  payees: number;
  money_inr: number;
  tiers: Record<string, number>;
  first_seen: string;
  last_seen: string;
  growing: boolean;
  examples: string[];
  review: { status: string; name: string | null; analyst: string; draft: string | null } | null;
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json() as Promise<T>;
}


/** Scam lab (/v1/lab/*, only when the API runs with --lab): the judge plays the scammer. */
export interface LabStatus {
  lab: boolean; adb: string | null; emulator: string | null;
  /** The demo account that paid most recently (the one signed in on the phone). */
  victim: string; victims: { user_id: string; name: string }[];
}
export interface LabWorkflow {
  id: string; title: string; flagged: boolean; story: string; expect: string; expect_tiers: Tier[];
  sms: { from: string; text: string } | null; call: string | null; victim_steps: string[];
  payee: string; amount: number; prepare: string;
}
export interface LabPresets {
  scam: { tag: string; lang: string; text: string }[];
  everyday: { lang: string; text: string }[];
  numbers: { unknown: string[]; contacts: { name: string; mobile: string }[] };
}
export interface LabLatest {
  payment: { payment_id: string; payee_upi: string; amount_inr: number; ts: string; tier: Tier;
    playbook: string | null; status: string; message_key: string | null } | null;
  reasons?: { code: string; text: string }[];
  headline?: string; lit?: string[]; result?: string; words?: string;
  expected?: { workflow: string; words: string; met: boolean; same_payee: boolean };
  victim?: string;
}
export interface LabSent { ts: string; kind: string; from?: string; number?: string; action?: string; chars?: number; workflow?: string }

async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    const detail = await r.json().then((j) => j.detail, () => null);
    throw new Error(typeof detail === "string" ? detail : `${path}: ${r.status}`);
  }
  return r.json() as Promise<T>;
}

/** The Accuracy page (GET /v1/accuracy, written by python -m evalsuite.accuracy). */
export interface AccuracyScorer {
  confusion: { scam_interrupted: number; scam_missed: number; legit_interrupted: number; legit_not_interrupted: number };
  scam_caught_rate: number; scam_rupees_caught_rate: number; false_alarms_per_1000: number;
  legit_tips_per_1000: number; precision: number | null; tiers: Record<string, number>;
  by_scam_type: Record<string, number>;
  missed_by_type: { scam_type: string; missed: number; of: number; median_inr: number | null; no_scam_message: number | null;
    no_call_during_payment: number | null; payee_older_than_90d: number | null; under_2000_inr: number | null }[];
}
export interface Accuracy {
  built_at: string; command: string;
  payments: { world: string; rows: number; scam_payments: number; legit_payments: number; live_scorer: string;
    rules_scorer: string; scorers: Record<string, AccuracyScorer> };
  messages: { model: string; held_out: string; messages: number; scam_caught: number; scam_right_type: number;
    scam_unclear: number; scam_called_normal: number; normal_false_alarm: number; normal_unclear: number;
    per_type_f1: Record<string, number>;
    by_language: Record<string, { messages: number; scam_caught: number; scam_called_normal: number; scam_unclear: number; normal_false_alarm: number }> };
  new_scams: { source: string; playbooks: number; scam_payments: number; missed: number; rules_missed: number;
    by_shape: Record<string, { playbooks: number; missed: number }>; examples: { name: string; title: string; missed: number }[] };
  failure_cases: { name: string; measured: string; why: string; fix: string }[];
}

export const api = {
  health: () => get<Health>("/health"),
  alerts: (minTier: Tier = "T1") => get<Alert[]>(`/v1/alerts?min_tier=${minTier}`),
  cases: () => get<EpisodeCase[]>("/v1/cases"),
  suspects: (minBand = "med") => get<Suspects>(`/v1/graph/suspects?min_band=${minBand}`),
  story: (upi: string) => get<Story>(`/v1/graph/story/${encodeURIComponent(upi.trim().toLowerCase())}`),
  verify: () => get<Verify>("/v1/evidence/verify"),
  payments: (upi: string) => get<PaymentList>(`/v1/graph/payments/${encodeURIComponent(upi.trim().toLowerCase())}`),
  /** null when no payment has that id (unknown, or older than 30 days). */
  payment: async (id: string) => {
    const r = await fetch(`/v1/payments/${encodeURIComponent(id.trim())}`, { headers: { Accept: "application/json" } });
    if (r.status === 404) return null;
    if (!r.ok) throw new Error(`payment: ${r.status}`);
    return r.json() as Promise<Payment>;
  },
  transactions: (params: { min_tier?: Tier | "T0"; status?: string; payee?: string; user_hash?: string; limit?: number } = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)]));
    return get<{ count: number; transactions: Transaction[] }>(`/v1/transactions?${q}`);
  },
  received: (params: { sender?: string; user_hash?: string; limit?: number } = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)]));
    return get<{ count: number; received: Received[] }>(`/v1/received?${q}`);
  },
  explain: (id: string) => get<Explanation>(`/v1/payments/${encodeURIComponent(id)}/explain`),
  alertHealth: () => get<AlertHealth>("/v1/metrics/alerts"),
  spreading: () => get<Spreading>("/v1/campaigns/spreading"),
  demoRun: async () => {
    const r = await fetch("/v1/demo/run", { method: "POST" });
    if (!r.ok) throw new Error(`demo: ${r.status}`);
    return r.json() as Promise<{ started: boolean; reason?: string }>;
  },
  demoResults: () => get<{ running: boolean; error: string | null; started: string | null;
    results: { scenario: string; expect: string; tiers: string[]; playbooks: string[]; ok: boolean }[] | null }>("/v1/demo/results"),
  /** false when the API was started without --lab. */
  labStatus: async (): Promise<LabStatus | false> => {
    const r = await fetch("/v1/lab/status");
    if (r.status === 404) return false;
    if (!r.ok) throw new Error(`lab: ${r.status}`);
    return r.json() as Promise<LabStatus>;
  },
  labPresets: (victim?: string) => get<LabPresets>(`/v1/lab/presets${victim ? `?victim=${victim}` : ""}`),
  labWorkflows: (victim?: string) => get<{ victim: string; workflows: LabWorkflow[]; app_switches: string[] }>(
    `/v1/lab/workflows${victim ? `?victim=${victim}` : ""}`),
  labSms: (from: string, text: string) => post<{ sent: boolean }>("/v1/lab/sms", { from, text }),
  labCall: (number: string, action: "ring" | "answer" | "hangup") => post<{ done: boolean }>("/v1/lab/call", { number, action }),
  labPrepare: (id: string, victim?: string) => post<Record<string, unknown>>(`/v1/lab/workflows/${id}/prepare${victim ? `?victim=${victim}` : ""}`),
  labSend: (id: string, victim?: string) => post<Record<string, unknown>>(`/v1/lab/workflows/${id}/send${victim ? `?victim=${victim}` : ""}`),
  labLatest: (workflow?: string, victim?: string) => {
    const q = new URLSearchParams();
    if (workflow) q.set("workflow", workflow);
    if (victim) q.set("user_id", victim);
    return get<LabLatest>(`/v1/lab/latest?${q}`);
  },
  labSent: () => get<{ sent: LabSent[] }>("/v1/lab/sent"),
  labReset: () => post<{ ok: boolean }>("/v1/lab/reset"),
  /** null until python -m evalsuite.accuracy has been run. */
  accuracy: async () => {
    const r = await fetch("/v1/accuracy");
    if (r.status === 404) return null;
    if (!r.ok) throw new Error(`accuracy: ${r.status}`);
    return r.json() as Promise<Accuracy>;
  },
  rings: () => get<{ as_of: string; rings: Ring[] }>("/v1/graph/rings"),
  emerging: () => get<{ as_of: string; patterns: EmergingPattern[] }>("/v1/patterns/emerging"),
  reviewPattern: async (id: string, analyst: string, action: "name" | "dismiss", name?: string) => {
    const r = await fetch(`/v1/patterns/${encodeURIComponent(id)}/review`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ analyst, action, name }),
    });
    if (!r.ok) throw new Error(`pattern review: ${r.status}`);
    return r.json() as Promise<{ pattern_id: string; status: string; name: string | null; draft_playbook: string | null }>;
  },
  review: async (upi: string, reviewer: string, decision: "approve" | "reject") => {
    const r = await fetch(`/v1/graph/suspects/${encodeURIComponent(upi)}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reviewer, decision }),
    });
    if (!r.ok) throw new Error(`review: ${r.status}`);
    return r.json() as Promise<Review & { upi_id: string }>;
  },
};
