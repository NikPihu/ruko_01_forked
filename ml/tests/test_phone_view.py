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
ALL_ON = Traits(call_signals=True, app_checks=True, sms=True, share_accounts=True, session_signals=True,
                android_15=True)
OFF = Traits(call_signals=False, app_checks=False, sms=False, share_accounts=False, session_signals=False,
             android_15=True)
SESSION = {"amount_digits": 5, "amount_median_gap_s": 3.1, "amount_max_gap_s": 6.0, "amount_gap_vs_usual": 4.2,
           "amount_edits": 1, "payee_pasted": True, "pasted_within_s_of_return": 4.0, "app_switches": 2,
           "away_s": 41.0, "pay_screen_s": 210.0, "abandoned_flows_30m": 1}


def view(events=(), traits=ALL_ON) -> PhoneView:
    users = pd.DataFrame({"user_id": ["u1"], "upi_id": ["u1@ybl"], "age_band": ["60+"]})
    accounts = pd.DataFrame({"upi_id": ["u1@ybl", "shop@okaxis"], "holder_type": ["person", "merchant"]})
    ev = pd.DataFrame([{"ts": ts, "user_id": "u1", "event_type": et, "attrs": json.dumps(at)}
                       for ts, et, at in events], columns=["ts", "user_id", "event_type", "attrs"])
    led = pd.DataFrame(columns=["ts", "from_upi", "to_upi", "amount"])
    v = PhoneView({"users": users, "accounts": accounts, "context_events": ev, "ledger": led}, seed=0)
    v.traits["u1"] = traits
    return v


def call(start, minutes, number, kind="sim", direction="incoming", in_contacts=False):
    at = {"caller_number": number, "call_kind": kind, "in_contacts": in_contacts, "direction": direction}
    end = start + timedelta(minutes=minutes)
    return [(start, "call_started", at), (end, "call_ended", {**at, "duration_min": minutes})]


def ctx(v: PhoneView, at=T, episode=None):
    return v.context_at("u1", at.timestamp(), episode)


def test_voip_call_has_no_number_and_unknown_contact_status():
    c, raw = ctx(view(call(T - timedelta(minutes=38), 90, FOREIGN, kind="voip")))
    assert (c.call.active, c.call.kind, c.call.started_min_ago) == (True, "voip", 38.0)
    assert c.call.caller_in_contacts is None and c.call.caller_number is None and c.call.direction is None
    assert c.call.speaker_on is None  # the simulator has no loudspeaker: unknown
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
    c, _ = ctx(view(call(T - timedelta(minutes=5), 30, STRANGER), traits=OFF))
    assert c is None
    apps_only = Traits(call_signals=False, app_checks=True, sms=False, share_accounts=False,
                       session_signals=False, android_15=True)
    c, _ = ctx(view(traits=apps_only))
    assert c.call is None and c.device is not None and c.lures == []
    assert c.episode is None and c.session is None


@pytest.mark.parametrize("android_15,session,expected", [(True, True, True), (True, False, False),
                                                         (False, True, None)])
def test_remote_access_active_needs_the_android_15_capture_callback(android_15, session, expected):
    events = [(T - timedelta(minutes=25), "app_installed",
               {"pkg": "com.anydesk.anydeskandroid", "is_remote_access": True, "sideloaded": False})]
    if session:
        events.append((T - timedelta(minutes=22), "remote_session_notice", {"pkg": "com.anydesk.anydeskandroid"}))
    tr = Traits(call_signals=True, app_checks=True, sms=True, share_accounts=False, session_signals=True,
                android_15=android_15)
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


def test_session_is_the_payments_own_pay_session_event_and_respects_the_switch():
    events = [(T, "pay_session", SESSION), (T - timedelta(minutes=9), "pay_session", {**SESSION, "app_switches": 0})]
    c, _ = ctx(view(events))
    assert c.session.model_dump() == SESSION
    no_session = Traits(call_signals=True, app_checks=True, sms=True, share_accounts=False,
                        session_signals=False, android_15=True)
    c, _ = ctx(view(events, traits=no_session))
    assert c.session is None


def test_episode_summary_is_sent_as_is():
    ep = {"state": "active", "age_days": 2.5, "bait_credits": 3, "bait_inr": 450.0, "outs": 3, "outs_inr": 9500.0,
          "new_payees": 3, "escalation_steps": 2, "last_out_inr": 6000.0, "out_to_in_ratio": 21.11,
          "payee_seen_in_episode": False, "rules_version": "episode-0.2"}
    c, raw = ctx(view(traits=OFF), episode=ep)  # the watcher's summary alone is enough for a context
    assert c.episode.model_dump() == ep and raw["episode"] is ep


def contacts_view(traits=ALL_ON) -> PhoneView:
    """u1 has paid her son (number-style UPI ID) and gets money from a friend; the mule is a stranger."""
    users = pd.DataFrame({"user_id": ["u1"], "upi_id": ["u1@ybl"], "age_band": ["60+"]})
    accounts = pd.DataFrame({
        "upi_id": ["u1@ybl", "9812345670@ybl", "friend.k@okaxis", "secure.desk@okaxis", "shop@okaxis"],
        "holder_type": ["person", "person", "person", "person", "merchant"],
        "mobile": ["+919000000001", "+919812345670", "+919811111111", "+919822222222", "+919833333333"],
        "is_mule": [False, False, False, True, False]})
    led = pd.DataFrame({"ts": [T - timedelta(days=3), T - timedelta(days=2)],
                        "from_upi": ["u1@ybl", "friend.k@okaxis"], "to_upi": ["9812345670@ybl", "u1@ybl"],
                        "amount": [2000.0, 500.0]})
    ev = pd.DataFrame(columns=["ts", "user_id", "event_type", "attrs"])
    v = PhoneView({"users": users, "accounts": accounts, "context_events": ev, "ledger": led}, seed=0)
    v.traits["u1"] = traits
    return v


@pytest.mark.parametrize("payee,entry,expected", [
    ("friend.k@okaxis", "contact", True),       # paid by mobile number: the friend is saved
    ("9812345670@ybl", "typed", True),          # the number inside a mobile-style UPI ID is saved
    ("friend.k@okaxis", "typed", False),        # a name-style UPI ID typed by hand: no number to match
    ("secure.desk@okaxis", "contact", False),   # mules are never in the address book
    ("shop@okaxis", "qr", False),
])
def test_payee_in_contacts_follows_contact_match(payee, entry, expected):
    c, raw = contacts_view().context_at("u1", T.timestamp(), payee=payee, entry=entry)
    assert c.payee_in_contacts is expected and raw["payee_in_contacts"] is expected


def test_payee_in_contacts_is_null_without_call_checks():
    no_calls = Traits(call_signals=False, app_checks=False, sms=False, share_accounts=False,
                      session_signals=False, android_15=True)
    c, raw = contacts_view(no_calls).context_at("u1", T.timestamp(), payee="friend.k@okaxis", entry="contact")
    assert c is None and raw["payee_in_contacts"] is None


def test_device_features_are_all_null_when_scam_shield_is_off():
    f = device_features({"call": None, "device": None, "lure_hits": None, "episode": None, "session": None},
                        {"ts": [], "amounts": [], "payees": set(), "p95": None, "max": None, "median": None},
                        500.0, "qr", "shop@okaxis", T.timestamp(), any_shield=False)
    assert set(f) == set(ALL) and all(v is None for v in f.values())


def test_device_features_keep_unknown_session_fields_unknown():
    raw = {"call": None, "device": None, "lure_hits": None, "episode": None,
           "session": {**SESSION, "amount_gap_vs_usual": None, "pasted_within_s_of_return": None}}
    hist = {"ts": [], "amounts": [], "payees": set(), "p95": None, "max": None, "median": None}
    f = device_features(raw, hist, 95_000.0, "typed", "mule@okaxis", T.timestamp(), any_shield=True)
    assert f["dev_sess_gap_vs_usual"] is None and f["dev_sess_paste_after_return_s"] is None
    assert f["dev_sess_pasted"] == 1.0 and f["dev_sess_app_switches"] == 2.0
    assert f["dev_amount_to_p95"] is None  # no history: unknown, not "normal"
    assert f["dev_ep_state"] is None and f["dev_lure_max"] is None
