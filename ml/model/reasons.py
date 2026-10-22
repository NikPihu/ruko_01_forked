"""Which reason code each server feature speaks for. Reasons come only from lit families, ranked by
how much each feature pushed this payment's family score up (LightGBM per-feature contributions).

Every model feature except `trusted_payee` (a policy rule, never a reason) must be listed here;
tests/test_predict.py checks that, and that every code is a contract ReasonCode.
"""
from __future__ import annotations

REASON = {
    # C: who is on the line, and who can see the screen
    "on_call": "R1_live_unknown_call", "caller_unknown": "R1_live_unknown_call", "voip_call": "R1_live_unknown_call",
    "foreign_caller": "R1_live_unknown_call", "outgoing_to_unknown": "R1_live_unknown_call",
    "call_on_speaker": "R1_live_unknown_call",
    "remote_control": "R2_remote_control", "untrusted_accessibility": "R2_remote_control",
    "sideloaded_last_24h": "R2_remote_control",
    # L: the hook (a scam-script SMS) and the task-scam episode
    "lure_max_conf_72h": "R5_lure_message", "lure_is_arrest_threat": "R5_lure_message", "lure_is_kyc": "R5_lure_message",
    "lure_is_task_job": "R5_lure_message", "lure_is_trading_tip": "R5_lure_message", "lure_is_refund": "R5_lure_message",
    "episode_state": "R10_bait_then_pay", "episode_age_days": "R10_bait_then_pay",
    "episode_bait_credits": "R10_bait_then_pay", "episode_new_payees": "R10_bait_then_pay",
    "episode_out_to_in": "R10_bait_then_pay", "episode_escalation_steps": "R10_bait_then_pay",
    # P: the payee, as its bank, the lists and the payment graph see it
    "payee_is_person": "R3_mule_like_payee", "payee_verified_merchant": "R3_mule_like_payee",
    "payee_account_age_days": "R3_mule_like_payee", "payee_uniq_payers_6h": "R3_mule_like_payee",
    "payee_uniq_payers_7d": "R3_mule_like_payee", "payee_repeat_ratio": "R3_mule_like_payee",
    "payee_pass_through_24h": "R3_mule_like_payee", "payee_median_hold_min": "R3_mule_like_payee",
    "payee_mulehunter": "R3_mule_like_payee", "vpa_invalid": "R3_mule_like_payee",
    "payee_registry_listed": "R8_intel_hit", "payee_fri_level": "R8_intel_hit",
    "caller_registry_listed": "R8_intel_hit", "caller_fri_level": "R8_intel_hit",
    "story_mismatch": "R9_story_mismatch",
    "payee_crowd": "R11_ring_link", "payee_money_loop": "R11_ring_link",
    "payee_forwards_to_cashout": "R11_ring_link", "payee_approved_suspect": "R11_ring_link",
    # B: this payment against the payer's own habits, and the Pay screen
    "amount_inr": "R4_unusual_amount", "amount_to_max_90d": "R4_unusual_amount",
    "amount_to_median_90d": "R4_unusual_amount",
    "first_time_payee": "R6_new_payee_typed", "entry_typed": "R6_new_payee_typed",
    "payee_in_contacts": "R6_new_payee_typed",
    "attempts_72h": "R7_tranche_pattern", "new_payee_sum_to_max_90d": "R7_tranche_pattern",
    "payee_in_run": "R7_tranche_pattern",
    "session_dictated": "R12_coached_session", "session_pasted_after_switch": "R12_coached_session",
    "session_app_switches": "R12_coached_session", "session_hesitation": "R12_coached_session",
    "session_abandoned_30m": "R12_coached_session",
}
NOT_A_REASON = {"trusted_payee"}
