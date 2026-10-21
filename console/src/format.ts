// Formatting shared by every page. Money in Indian grouping, times in IST, words over codes.

export function inr(x: number | null | undefined): string {
  if (x == null || Number.isNaN(x)) return "—";
  return "₹" + Math.round(x).toLocaleString("en-IN");
}

export function inrShort(x: number): string {
  if (x >= 1e7) return `₹${(x / 1e7).toFixed(1)} Cr`;
  if (x >= 1e5) return `₹${(x / 1e5).toFixed(1)} L`;
  if (x >= 1e3) return `₹${(x / 1e3).toFixed(1)}k`;
  return inr(x);
}

export function pct(x: number | null | undefined, digits = 0): string {
  if (x == null || Number.isNaN(x)) return "—";
  return `${(x * 100).toFixed(digits)}%`;
}

const DT = new Intl.DateTimeFormat("en-IN", {
  day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata",
});

export function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : DT.format(d);
}

/** What the user did after the check, as reported by the phone (c2-0.6). */
export const PAYMENT_STATUS: Record<string, string> = {
  completed: "Paid",
  cancelled: "Cancelled",
  checked: "Not reported yet",
};

/** A payment id (UUID) shortened for tables; the full id is in the tooltip and on the detail. */
export function shortId(id: string): string {
  return id.length > 13 ? `${id.slice(0, 8)}…` : id;
}

/** A pseudonymised user id, shortened so it reads as a label rather than a hash. */
export function userLabel(hash: string): string {
  return "User " + hash.replace(/^u:/, "").slice(0, 6);
}

export const STAGES: Record<string, string> = {
  S0: "Nothing yet",
  S1: "Contacted",
  S2: "Hooked",
  S3: "Under control",
  S4: "Paying",
  S5: "Paying again",
};

export const PLAYBOOKS: Record<string, string> = {
  digital_arrest: "Digital arrest",
  task_job: "Task / job scam",
  trading_group: "Trading group",
  fake_kyc_apk: "Fake KYC app",
  refund_qr: "Refund QR",
  fake_customer_care: "Fake customer care",
};

export const TIERS: Record<string, { name: string; action: string }> = {
  T0: { name: "Allowed", action: "Paid without a prompt" },
  T1: { name: "Tip", action: "Inline tip shown" },
  T2: { name: "Warned", action: "Explanation card, slide to pay" },
  T3: { name: "Paused", action: "30-minute pause, call a trusted person or 1930" },
  T4: { name: "Held for review", action: "Held for an analyst" },
};
