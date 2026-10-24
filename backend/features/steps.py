"""Scam steps (contracts/steps.json): what a payment's journey showed, in one vocabulary shared by
the phone's verdict, the engine, the playbooks and the blue team.

Every step is True (seen), False (measured, not seen) or None (not measured: the switch is off,
no permission, too little history). None is never False (CLAUDE.md rule 1).

- `phone_steps(dev)`: from the on-device model's features (ml/dataset/device_features.py), what the
  phone puts in its verdict (c2-0.14 `steps_seen`). android/.../signals/Steps.kt is a line-by-line
  port, checked by contracts/examples/steps_vectors.json.
- `server_steps(f, req)`: from the engine's features (features/build.py) and the request.
- `merge(*readings)`: one reading per step: True if any reading saw it, False if one measured it
  and none saw it, None if no one measured it.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from features.session import dictated, hesitation, pasted_after_switch
from schema.events import SessionSignal

VOCAB_PATH = Path(__file__).resolve().parents[2] / "contracts" / "steps.json"
VOCAB = json.loads(VOCAB_PATH.read_text(encoding="utf-8"))
P = VOCAB["params"]
STEP_IDS: tuple[str, ...] = tuple(s["id"] for s in VOCAB["steps"])
STAGE = {s["id"]: s["stage"] for s in VOCAB["steps"]}
LURE_TAGS = ("arrest_threat", "kyc", "task_job", "trading_tip", "refund", "other_scam")
# The phone's lure features (ml/dataset/device_features.py LURE_TAG_FEATURE; other_scam / unclear from lure-0.2).
DEV_LURE = {"arrest_threat": "dev_lure_arrest", "kyc": "dev_lure_kyc", "task_job": "dev_lure_task",
            "trading_tip": "dev_lure_trading", "refund": "dev_lure_refund", "other_scam": "dev_lure_other_scam"}
# contracts/README.md `session` field -> device feature (the same numbers the phone measured).
DEV_SESSION = {"amount_digits": "dev_sess_digits", "amount_median_gap_s": "dev_sess_median_gap_s",
               "amount_max_gap_s": "dev_sess_max_gap_s", "amount_gap_vs_usual": "dev_sess_gap_vs_usual",
               "amount_edits": "dev_sess_edits", "payee_pasted": "dev_sess_pasted",
               "pasted_within_s_of_return": "dev_sess_paste_after_return_s", "app_switches": "dev_sess_app_switches",
               "away_s": "dev_sess_away_s", "pay_screen_s": "dev_sess_pay_screen_s",
               "abandoned_flows_30m": "dev_sess_abandoned_30m"}
INT_SESSION = {"amount_digits", "amount_edits", "app_switches", "abandoned_flows_30m"}


def round1(x: float) -> float:
    """Half up to one decimal, the same in Kotlin (floor(x * 10 + 0.5) / 10)."""
    return math.floor(x * 10 + 0.5) / 10


def _on(x) -> bool | None:
    """A 0/1 (or bool) reading -> bool; None stays None."""
    return None if x is None else bool(x >= 0.5) if isinstance(x, (int, float)) and not isinstance(x, bool) else bool(x)


def _ge(x, t) -> bool | None:
    return None if x is None else x >= t


def _and(*xs) -> bool | None:
    """Three-valued AND: False if any is False, else None if any is None, else True."""
    if any(x is False for x in xs):
        return False
    return None if any(x is None for x in xs) else True


def _or(*xs) -> bool | None:
    if any(x is True for x in xs):
        return True
    return None if any(x is None for x in xs) else False


# ---- the phone -----------------------------------------------------------------------------------

def phone_steps(dev: dict) -> dict[str, tuple[bool | None, float | None]]:
    """{step: (seen, minutes ago or None)} for every step the phone can measure, from its device
    features. Steps only the server can see are left out."""
    out: dict[str, tuple[bool | None, float | None]] = {}
    g = dev.get
    active, ended = _on(g("dev_call_active")), g("dev_call_ended_min_ago")
    recent = None if active is None else (active or (ended is not None and ended <= P["recent_call_min"]))
    call_ago = None if not recent else (0.0 if active else ended)
    voip = _on(g("dev_call_voip"))
    # A VoIP call never shows its number: contact status unknown counts as an unknown caller (features.build).
    unknown = _on(g("dev_call_unknown"))
    if unknown is None and voip:
        unknown = True
    out["unknown_call"] = (_and(recent, unknown), call_ago)
    out["voip_call"] = (_and(recent, voip), call_ago)
    incoming = _on(g("dev_call_incoming"))
    out["call_out_to_unknown"] = (_and(out["unknown_call"][0], None if incoming is None else not incoming), call_ago)
    out["long_call"] = (_and(recent, _ge(g("dev_call_minutes"), P["long_call_min"])), call_ago)
    out["foreign_call"] = (_and(recent, _on(g("dev_call_foreign"))), call_ago)

    lure_ago = g("dev_lure_min_ago")
    for tag, name in DEV_LURE.items():
        if name in dev or tag != "other_scam":
            seen = _ge(g(name), P["lure_min_conf"])
            out[f"lure:{tag}"] = (seen, lure_ago if seen else None)
    if "dev_lure_unclear" in dev:
        seen = _on(g("dev_lure_unclear"))
        out["lure:unclear"] = (seen, lure_ago if seen else None)

    state = g("dev_ep_state")
    out["bait_credit"] = (_ge(g("dev_ep_bait_credits"), 1), None)
    out["episode_watching"] = (None if state is None else state == 1, None)
    out["episode_active"] = (None if state is None else state == 2, None)
    out["escalating_payments"] = (_ge(g("dev_ep_escalation"), 1), None)

    rec = _on(g("dev_screen_recorded"))
    rmin = g("dev_remote_min_ago")
    remote_recent = None if g("dev_remote_installed") is None else (rmin is not None and rmin <= P["remote_recent_min"])
    out["remote_control"] = (_or(rec, remote_recent), None)
    out["untrusted_accessibility"] = (_on(g("dev_accessibility")), None)
    out["sideload_24h"] = (_on(g("dev_sideloaded_24h")), None)

    sess = _session(dev)
    if sess is None:
        for k in ("dictated_amount", "paste_after_switch", "many_app_switches", "long_hesitation", "abandoned_tries"):
            out[k] = (None, None)
    else:
        out["dictated_amount"] = (dictated(sess), 0.0)
        out["paste_after_switch"] = (pasted_after_switch(sess), 0.0)
        out["many_app_switches"] = (_ge(sess.app_switches, P["many_app_switches"]), 0.0)
        out["long_hesitation"] = (hesitation(sess), 0.0)
        out["abandoned_tries"] = (_ge(sess.abandoned_flows_30m, 1), None)

    after = None if active is None else (not active and ended is not None
                                         and P["after_call_min_from"] <= ended <= P["recent_call_min"])
    out["paid_after_call"] = (_and(after, unknown), ended if after else None)
    out["new_payee"] = (_on(g("dev_first_time_payee")), None)
    out["amount_unusual"] = (_ge(g("dev_amount_to_max"), P["amount_unusual_vs_max"]), None)
    return {k: (seen, (round1(ago) if isinstance(ago, (int, float)) and seen else None)) for k, (seen, ago) in out.items()}


def _session(dev: dict) -> SessionSignal | None:
    vals = {k: dev.get(v) for k, v in DEV_SESSION.items()}
    if all(v is None for v in vals.values()):
        return None
    clean = {}
    for k, v in vals.items():
        if v is None:
            continue
        clean[k] = bool(v) if k == "payee_pasted" else int(round(v)) if k in INT_SESSION else float(v)
    return SessionSignal(**clean)


def verdict_steps(dev: dict) -> tuple[list[dict], list[str]]:
    """The verdict's steps_seen ([{step, min_ago}], vocabulary order) and steps_unmeasured."""
    ps = phone_steps(dev)
    seen = [{"step": s, "min_ago": ps[s][1]} for s in STEP_IDS if s in ps and ps[s][0] is True]
    unmeasured = [s for s in STEP_IDS if s in ps and ps[s][0] is None]
    return seen, unmeasured


# ---- the server ----------------------------------------------------------------------------------

def server_steps(f: dict, req=None) -> dict[str, bool | None]:
    """{step: seen} from the engine's features (features/build.py) and the request itself."""
    g = f.get
    out: dict[str, bool | None] = {}
    on_call = g("on_call")
    unknown = None if on_call is None else (bool(on_call) and (bool(g("caller_unknown"))
                                                                or (bool(g("voip_call")) and g("caller_unknown") is None)))
    out["unknown_call"] = unknown
    out["voip_call"] = _and(on_call, _on(g("voip_call")))
    out["video_call"] = _and(on_call, _on(g("video_call")))
    out["call_out_to_unknown"] = _on(g("outgoing_to_unknown"))
    out["foreign_call"] = _and(on_call, _on(g("foreign_caller")))
    out["caller_in_campaign"] = _on(g("caller_in_campaign"))

    lures = None
    if req is not None and req.context is not None:
        lures = {l.tag: l.conf for l in req.context.lures}
    for tag in LURE_TAGS:
        out[f"lure:{tag}"] = None if lures is None else (lures.get(tag, 0.0) >= P["lure_min_conf"])

    state = g("episode_state")
    out["bait_credit"] = _ge(g("episode_bait_credits"), 1)
    out["episode_watching"] = None if state is None else state == 1
    out["episode_active"] = None if state is None else state == 2
    out["escalating_payments"] = _ge(g("episode_escalation_steps"), 1)
    out["remote_control"] = _on(g("remote_control"))
    out["untrusted_accessibility"] = _on(g("untrusted_accessibility"))
    out["sideload_24h"] = _on(g("sideloaded_last_24h"))

    out["dictated_amount"] = _on(g("session_dictated"))
    out["paste_after_switch"] = _on(g("session_pasted_after_switch"))
    out["many_app_switches"] = _ge(g("session_app_switches"), P["many_app_switches"])
    out["long_hesitation"] = _on(g("session_hesitation"))
    out["abandoned_tries"] = _ge(g("session_abandoned_30m"), 1)

    out["new_payee"] = _on(g("first_time_payee"))
    entry = getattr(req, "entry_method", None)
    for step, kind in (("qr_entry", "qr"), ("contact_entry", "contact"), ("typed_entry", "typed")):
        out[step] = None if entry is None else entry == kind
    amount = g("amount_inr")
    out["amount_unusual"] = _ge(g("amount_to_max_90d"), P["amount_unusual_vs_max"])
    out["amount_small"] = None if amount is None else amount < P["amount_small_inr"]
    out["amount_large"] = _ge(amount, P["amount_large_inr"])
    out["repeat_attempts"] = _ge(g("attempts_72h"), P["repeat_attempts"])
    out["anchor_then_drain"] = _on(g("payee_micro_anchor"))
    out["outflow_burst"] = _ge(g("outflow_24h_to_max_90d"), P["outflow_burst_vs_max"])

    age = g("payee_account_age_days")
    out["young_account"] = None if age is None else age < P["young_account_days"]
    out["many_payers"] = _ge(g("payee_uniq_payers_6h"), P["many_payers_6h"])
    out["pass_through"] = _ge(g("payee_pass_through_24h"), P["pass_through"])
    out["mulehunter_high"] = _ge(g("payee_mulehunter"), P["mulehunter_high"])
    out["registry_listed"] = _on(g("payee_registry_listed"))
    out["new_and_spreading"] = _on(g("payee_new_and_spreading"))
    out["in_campaign"] = _on(g("payee_in_campaign"))
    out["ring_member"] = _or(_on(g("payee_money_loop")), _on(g("payee_forwards_to_cashout")), _on(g("payee_approved_suspect")))
    out["automated"] = _on(g("payee_automated"))
    return out


def merge(*readings: dict) -> dict[str, bool | None]:
    """Readings of the same payment ({step: seen} or {step: (seen, min_ago)}) -> one {step: seen}."""
    out: dict[str, bool | None] = {}
    for r in readings:
        for k, v in (r or {}).items():
            v = v[0] if isinstance(v, tuple) else v
            old = out.get(k)
            out[k] = True if True in (old, v) else False if False in (old, v) else None
    return out


def from_verdict(dv) -> dict[str, bool | None]:
    """The phone's verdict (c2-0.14 steps_seen / steps_unmeasured) as {step: seen}. A step the phone
    measures that is neither seen nor unmeasured was measured and not seen."""
    if dv is None or getattr(dv, "steps_seen", None) is None:
        return {}
    seen = {s.step for s in dv.steps_seen}
    unmeasured = set(dv.steps_unmeasured or [])
    phone = [s["id"] for s in VOCAB["steps"] if s["seen_by"] in ("phone", "both")]
    return {k: (True if k in seen else None if k in unmeasured else False) for k in phone}
