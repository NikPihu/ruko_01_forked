"""Scam steps (contracts/steps.json, features/steps.py): one vocabulary, three-valued readings."""
from __future__ import annotations

import yaml

from features import steps
from features.session import POLICY_YAML


def test_vocabulary_is_well_formed():
    ids = [s["id"] for s in steps.VOCAB["steps"]]
    assert len(ids) == len(set(ids))
    assert {s["stage"] for s in steps.VOCAB["steps"]} <= set(steps.VOCAB["stages"])
    assert {s["seen_by"] for s in steps.VOCAB["steps"]} <= {"phone", "server", "both"}


def test_the_phones_session_thresholds_are_policy_yamls():
    policy = yaml.safe_load(POLICY_YAML.read_text())["session"]
    mine = {k: v for k, v in steps.P["session"].items() if k != "about"}
    assert mine == policy


def test_every_step_is_defined_on_the_side_that_sees_it():
    dev = {"dev_lure_other_scam": 0.0, "dev_lure_unclear": 0.0}
    phone, server = set(steps.phone_steps(dev)), set(steps.server_steps({}))
    for s in steps.VOCAB["steps"]:
        if s["seen_by"] in ("phone", "both"):
            assert s["id"] in phone, s["id"]
        if s["seen_by"] in ("server", "both"):
            assert s["id"] in server, s["id"]


def dev(**kw) -> dict:
    base = {"dev_call_active": 0.0, "dev_call_voip": None, "dev_call_unknown": None, "dev_call_incoming": None,
            "dev_call_minutes": None, "dev_call_ended_min_ago": None, "dev_call_foreign": None,
            "dev_remote_installed": 0.0, "dev_remote_min_ago": None, "dev_screen_recorded": 0.0,
            "dev_accessibility": 0.0, "dev_sideloaded_24h": 0.0, "dev_lure_max": 0.0, "dev_lure_arrest": 0.0,
            "dev_lure_kyc": 0.0, "dev_lure_task": 0.0, "dev_lure_trading": 0.0, "dev_lure_refund": 0.0,
            "dev_lure_count_72h": 0.0, "dev_lure_min_ago": None, "dev_ep_state": 0.0, "dev_ep_bait_credits": 0.0,
            "dev_ep_escalation": 0.0, "dev_first_time_payee": 1.0, "dev_payee_in_contacts": None,
            "dev_amount_to_max": None}
    return {**base, **kw}


def seen(d: dict) -> dict:
    return {k: v[0] for k, v in steps.phone_steps(d).items()}


def test_no_call_is_measured_not_seen_and_switches_off_are_unknown():
    s = seen(dev())
    assert s["unknown_call"] is False and s["paid_after_call"] is False and s["new_payee"] is True
    off = seen(dev(dev_call_active=None, dev_screen_recorded=None, dev_remote_installed=None,
                   dev_lure_max=None, dev_lure_arrest=None, dev_ep_state=None))
    assert off["unknown_call"] is None and off["remote_control"] is None and off["lure:arrest_threat"] is None
    assert off["episode_active"] is None and off["dictated_amount"] is None     # session checks off


def test_a_whatsapp_call_is_an_unknown_caller_and_the_cool_off_counts():
    now = steps.phone_steps(dev(dev_call_active=1.0, dev_call_voip=1.0, dev_call_unknown=None, dev_call_minutes=38.0,
                                dev_call_incoming=1.0))
    assert now["unknown_call"] == (True, 0.0) and now["voip_call"][0] and now["long_call"][0]
    assert now["call_out_to_unknown"][0] is False and now["paid_after_call"][0] is False
    later = steps.phone_steps(dev(dev_call_active=0.0, dev_call_voip=1.0, dev_call_ended_min_ago=42.26))
    assert later["paid_after_call"] == (True, 42.3) and later["unknown_call"] == (True, 42.3)
    too_soon = seen(dev(dev_call_active=0.0, dev_call_voip=1.0, dev_call_ended_min_ago=2.0))
    assert too_soon["paid_after_call"] is False and too_soon["unknown_call"] is True


def test_lures_control_hook_and_session():
    s = seen(dev(dev_lure_arrest=0.81, dev_lure_kyc=0.59, dev_lure_min_ago=12.0, dev_remote_installed=1.0,
                 dev_remote_min_ago=30.0, dev_ep_state=2.0, dev_ep_bait_credits=2.0,
                 dev_sess_digits=6.0, dev_sess_gap_vs_usual=3.1, dev_sess_pasted=1.0, dev_sess_paste_after_return_s=8.0,
                 dev_sess_app_switches=3.0, dev_sess_pay_screen_s=240.0, dev_sess_abandoned_30m=1.0))
    assert s["lure:arrest_threat"] and s["lure:kyc"] is False and s["remote_control"] and s["episode_active"]
    assert s["bait_credit"] and s["dictated_amount"] and s["paste_after_switch"] and s["many_app_switches"]
    assert s["long_hesitation"] and s["abandoned_tries"]
    assert "lure:other_scam" not in s and "lure:unclear" not in s          # the phone's lure model predates lure-0.2


def test_verdict_steps_lists_seen_and_unmeasured_in_vocabulary_order():
    seen_list, unmeasured = steps.verdict_steps(dev(dev_call_active=1.0, dev_call_unknown=1.0, dev_call_minutes=1.0,
                                                    dev_ep_state=None))
    names = [x["step"] for x in seen_list]
    assert names == [s for s in steps.STEP_IDS if s in names] and "unknown_call" in names and "new_payee" in names
    assert "episode_active" in unmeasured and "unknown_call" not in unmeasured


def test_server_steps_and_merge():
    f = {"on_call": True, "caller_unknown": None, "voip_call": True, "first_time_payee": True,
         "payee_account_age_days": 3, "payee_pass_through_24h": 0.9, "payee_micro_anchor": True, "amount_inr": 25000.0}
    s = steps.server_steps(f)
    assert s["unknown_call"] and s["young_account"] and s["pass_through"] and s["anchor_then_drain"] and s["amount_large"]
    assert s["registry_listed"] is None and s["qr_entry"] is None
    m = steps.merge(s, {"unknown_call": (False, None), "paid_after_call": (True, 40.0), "registry_listed": (None, None)})
    assert m["unknown_call"] is True and m["paid_after_call"] is True and m["registry_listed"] is None
    assert steps.merge({"x": False}, {"x": None})["x"] is False
