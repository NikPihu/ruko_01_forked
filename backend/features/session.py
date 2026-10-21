"""Coached-session signs (c2-0.5): the phone's Pay-screen numbers -> yes/no signs.

A person being talked through a payment behaves differently on the Pay screen: the amount is
typed digit by digit as it is read out, the UPI ID is pasted right after coming back from WhatsApp
or the call, the app is left again and again. The phone sends only counts and rounded times
(`context.session`); this module decides what they mean, with thresholds from api/policy.yaml.

`None` always means unknown (no session block, or the phone could not measure it), never "calm".
All signs are behaviour family (B). They never interrupt a payment on their own.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from schema.events import SessionSignal

POLICY_YAML = Path(__file__).resolve().parents[1] / "api" / "policy.yaml"
DEFAULTS = {"dictated_min_digits": 4, "dictated_vs_usual": 2.5, "dictated_no_baseline_median_s": 2.0,
            "dictated_no_baseline_max_s": 4.0, "paste_after_return_s": 20, "many_switches": 2,
            "hesitation_s": 180}


def load_thresholds(path: Path = POLICY_YAML) -> dict:
    cfg = yaml.safe_load(path.read_text()) or {}
    return {**DEFAULTS, **(cfg.get("session") or {})}


T = load_thresholds()


def dictated(s: SessionSignal, t: dict = T) -> bool | None:
    """Amount typed with long pauses between digits, as if someone is reading it out."""
    if s.amount_digits is None:
        return None
    if s.amount_digits < t["dictated_min_digits"]:
        return False
    if s.amount_gap_vs_usual is not None:  # compare with this person's own typing first
        return s.amount_gap_vs_usual >= t["dictated_vs_usual"]
    if s.amount_median_gap_s is None or s.amount_max_gap_s is None:
        return None
    return (s.amount_median_gap_s >= t["dictated_no_baseline_median_s"]
            and s.amount_max_gap_s >= t["dictated_no_baseline_max_s"])


def pasted_after_switch(s: SessionSignal, t: dict = T) -> bool | None:
    """UPI ID pasted soon after coming back to the app: copied from a chat or a call."""
    if s.payee_pasted is None:
        return None
    if not s.payee_pasted:
        return False
    if s.pasted_within_s_of_return is None:  # pasted, but the app never left: from this app's own clipboard
        return False if s.app_switches == 0 else None
    return s.pasted_within_s_of_return <= t["paste_after_return_s"]


def hesitation(s: SessionSignal, t: dict = T) -> bool | None:
    return None if s.pay_screen_s is None else s.pay_screen_s >= t["hesitation_s"]


def session_features(s: SessionSignal | None, t: dict = T) -> dict:
    if s is None:
        return {"session_dictated": None, "session_pasted_after_switch": None,
                "session_app_switches": None, "session_hesitation": None, "session_abandoned_30m": None}
    return {"session_dictated": dictated(s, t), "session_pasted_after_switch": pasted_after_switch(s, t),
            "session_app_switches": s.app_switches, "session_hesitation": hesitation(s, t),
            "session_abandoned_30m": s.abandoned_flows_30m}
