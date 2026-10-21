"""The rebuilt phone readings must follow the Android app's rules exactly."""
import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from dataset.device_features import ALL, device_features
from dataset.phone_view import PhoneView, Traits

IST = timezone(timedelta(hours=5, minutes=30))
T = datetime(2026, 11, 1, 10, 0, tzinfo=IST)
STRANGER, FOREIGN = "+919812345670", "+923001234567"
ALL_ON = Traits(call_signals=True, app_checks=True, sms=True, android_15=True, pace=1.0)


def view(events=(), payments=(), traits=ALL_ON) -> PhoneView:
    users = pd.DataFrame({"user_id": ["u1"], "upi_id": ["u1@ybl"], "age_band": ["60+"]})
    accounts = pd.DataFrame({"upi_id": ["u1@ybl", "shop@okaxis", "mule@okaxis", "bait@ybl"],
                             "holder_type": ["person", "merchant", "person", "person"]})
    ev = pd.DataFrame([{"ts": ts, "user_id": "u1", "event_type": et, "attrs": json.dumps(at)}
                       for ts, et, at in events], columns=["ts", "user_id", "event_type", "attrs"])
    led = pd.DataFrame([{"ts": ts, "from_upi": f, "to_upi": to, "amount": a} for ts, f, to, a in payments],
                       columns=["ts", "from_upi", "to_upi", "amount"])
    v = PhoneView({"users": users, "accounts": accounts, "context_events": ev, "ledger": led}, seed=0)
    v.traits["u1"] = traits
    return v


def call(start, minutes, number, kind="sim", direction="incoming", in_contacts=False):
    at = {"caller_number": number, "call_kind": kind, "in_contacts": in_contacts, "direction": direction}
    end = start + timedelta(minutes=minutes)
    return [(start, "call_started", at), (end, "call_ended", {**at, "duration_min": minutes})]


def ctx(v: PhoneView, at=T):
    return v.context_at("u1", at.timestamp())


def test_voip_call_has_no_number_and_unknown_contact_status():
    c, raw = ctx(view(call(T - timedelta(minutes=38), 90, FOREIGN, kind="voip")))
    assert (c.call.active, c.call.kind, c.call.started_min_ago) == (True, "voip", 38.0)
    assert c.call.caller_in_contacts is None and c.call.caller_number is None and c.call.direction is None
    assert raw["call"]["foreign"] is None  # the phone cannot know


def test_incoming_sim_call_from_a_stranger_sends_the_number():
    c, raw = ctx(view(call(T - timedelta(minutes=5), 30, STRANGER)))
    assert (c.call.caller_number, c.call.caller_in_contacts, c.call.direction) == (STRANGER, False, "incoming")
    assert raw["call"]["foreign"] is False


def test_contacts_and_outgoing_calls_never_send_a_number():
    c, _ = ctx(view(call(T - timedelta(minutes=5), 30, STRANGER, in_contacts=True)))
    assert c.call.caller_number is None and c.call.caller_in_contacts is True
    c, _ = ctx(view(call(T - timedelta(minutes=5), 30, STRANGER, direction="outgoing")))
    assert c.call.caller_number is None and c.call.caller_in_contacts is None
    assert c.call.direction == "outgoing"


def test_a_call_that_ended_within_30_minutes_still_counts():
    v = view(call(T - timedelta(minutes=60), 40, STRANGER))  # ended 20 min ago
    c, _ = ctx(v)
    assert (c.call.active, c.call.kind, c.call.ended_min_ago, c.call.caller_number) == (False, "sim", 20.0, STRANGER)
    c, _ = ctx(v, T + timedelta(minutes=11))  # 31 min after the end
    assert c.call.model_dump(exclude_none=True) == {"active": False}


def test_switched_off_groups_are_null_and_all_off_is_no_context():
    off = Traits(call_signals=False, app_checks=False, sms=False, android_15=True, pace=1.0)
    c, _ = ctx(view(call(T - timedelta(minutes=5), 30, STRANGER), traits=off))
    assert c is None
    apps_only = Traits(call_signals=False, app_checks=True, sms=False, android_15=True, pace=1.0)
    c, _ = ctx(view(traits=apps_only))
    assert c.call is None and c.device is not None and c.lures == []
    assert c.money is not None and c.money.bait_credits is None and c.money.credits_inr is None


@pytest.mark.parametrize("android_15,session,expected", [(True, True, True), (True, False, False),
                                                         (False, True, None)])
def test_remote_access_active_needs_the_android_15_capture_callback(android_15, session, expected):
    events = [(T - timedelta(minutes=25), "app_installed",
               {"pkg": "com.anydesk.anydeskandroid", "is_remote_access": True, "sideloaded": False})]
    if session:
        events.append((T - timedelta(minutes=22), "remote_session_notice", {"pkg": "com.anydesk.anydeskandroid"}))
    tr = Traits(call_signals=True, app_checks=True, sms=True, android_15=android_15, pace=1.0)
    c, _ = ctx(view(events, traits=tr))
    assert c.device.remote_access_active is expected
    assert c.device.remote_app_installed_min_ago == 25.0


def test_lures_sent_only_from_threshold_and_best_per_tag():
    events = [(T - timedelta(hours=h), "sms_lure", {"tag": tag, "conf": conf})
              for h, tag, conf in [(1, "kyc", 0.55), (2, "kyc", 0.7), (3, "kyc", 0.65), (4, "task_job", 0.9),
                                   (80, "arrest_threat", 0.95)]]  # the last one is older than 72 h
    c, raw = ctx(view(events))
    assert [(x.tag, x.conf) for x in c.lures] == [("task_job", 0.9), ("kyc", 0.7)]
    assert len(raw["lure_hits"]) == 4


def test_money_flow_counts_bait_and_escalation_like_the_app():
    pays = [(T - timedelta(hours=30), "bait@ybl", "u1@ybl", 150), (T - timedelta(hours=29), "bait@ybl", "u1@ybl", 200),
            (T - timedelta(hours=20), "u1@ybl", "mule@okaxis", 1000), (T - timedelta(hours=10), "u1@ybl", "mule@okaxis", 2500),
            (T - timedelta(hours=2), "u1@ybl", "mule@okaxis", 6000)]
    v = view(payments=pays)
    v.ledger.ins["u1@ybl"][3][:] = [True, True]  # both alerts parsed
    c, _ = ctx(v)
    m = c.money
    assert (m.bait_credits, m.debits, m.new_payees, m.escalation_steps, m.last_debit_inr) == (2, 3, 1, 2, 6000)
    no_sms = Traits(call_signals=True, app_checks=True, sms=False, android_15=True, pace=1.0)
    c, _ = ctx(view(payments=pays, traits=no_sms))
    assert c.money.bait_credits is None and c.money.debits == 3


def test_device_features_are_all_null_when_scam_shield_is_off():
    f = device_features({"call": None, "device": None, "lure_hits": None, "money": None},
                        {"ts": [], "amounts": [], "payees": set(), "p95": None, "max": None, "median": None},
                        500.0, "qr", "shop@okaxis", T.timestamp(), {}, any_shield=False)
    assert set(f) == set(ALL) and all(v is None for v in f.values())
