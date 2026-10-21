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

export interface EvalCondition {
  label: string;
  share_inr_interrupted: number;
  journeys_alerted: number;
  journeys: number;
  median_first_alert_payment: number | null;
  false_interruption_rate: number;
}

export interface EvalVisibility {
  mules_flagged: number;
  share_of_mules_flagged_before_registry: number;
  median_days_before_listing: number | null;
  analyst_list: number;
  analyst_list_precision: number;
  rings: number;
}

export interface EvalResults {
  episode: {
    world: { users: number; task_journeys: number; task_inr: number };
    conditions: Record<"known_mules" | "fresh_mules", Record<"A" | "B" | "C", EvalCondition>>;
  } | null;
  graph: {
    world: { users: number; mules: number; episode_events: number };
    visibility: Record<"none" | "partner" | "dpip", EvalVisibility>;
  } | null;
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json() as Promise<T>;
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
  evaluation: () => get<EvalResults>("/v1/eval"),
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
