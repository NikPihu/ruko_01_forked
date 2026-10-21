// Reason codes in words for analysts (contract C2). The phone shows its own Hindi/English
// versions; these say what RUKO saw, in the third person.

const TEXT: Record<string, { title: string; family: string }> = {
  R1_live_unknown_call: { title: "On a call with an unknown number while paying", family: "Context" },
  R2_remote_control: { title: "A screen-sharing or remote-control app was active", family: "Context" },
  R3_mule_like_payee: { title: "Payee looks like a mule: new, many unrelated payers, money moves on fast", family: "Payee" },
  R4_unusual_amount: { title: "Much larger than this person usually pays", family: "Behaviour" },
  R5_lure_message: { title: "A scam-script message arrived recently", family: "Lure" },
  R6_new_payee_typed: { title: "First payment to a UPI ID typed by hand", family: "Behaviour" },
  R7_tranche_pattern: { title: "Several payments in a short time (split into tranches)", family: "Behaviour" },
  R8_intel_hit: { title: "Account or number already reported (I4C / DoT)", family: "Payee" },
  R9_story_mismatch: { title: "Paying a private person while saying it's a government or company payment", family: "Payee" },
  R10_bait_then_pay: { title: "Small “rewards” came in, then bigger and bigger payments went out", family: "Lure" },
  R11_ring_link: { title: "Payee is linked to the account that sent the “rewards”", family: "Payee" },
  ruko_unavailable: { title: "RUKO could not decide in time; the payment went ahead", family: "System" },
};

export function reasonText(code: string): string {
  return TEXT[code]?.title ?? code;
}

export function reasonFamily(code: string): string {
  return TEXT[code]?.family ?? "Other";
}
