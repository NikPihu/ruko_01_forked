"""Coached-session signs (c2-0.5): behaviour-family evidence that never interrupts on its own."""
import json
from pathlib import Path

import pytest

from features.session import dictated, hesitation, pasted_after_switch, session_features
from schema.events import DecideRequest, SessionSignal
from test_decide import (MEENA_CONTEXT, UNKNOWN_CALLER, baseline, engine, mock, pump, req,  # noqa: F401
                         users_in, world)

COACHED = {"amount_digits": 5, "amount_median_gap_s": 2.4, "amount_max_gap_s": 6.1,
           "amount_gap_vs_usual": 4.8, "amount_edits": 1, "payee_pasted": True,
           "pasted_within_s_of_return": 6.0, "app_switches": 3, "away_s": 41.0,
           "pay_screen_s": 212.0, "abandoned_flows_30m": 1}
CALM = {"amount_digits": 4, "amount_median_gap_s": 0.4, "amount_max_gap_s": 0.9,
        "amount_gap_vs_usual": 1.0, "amount_edits": 0, "payee_pasted": False,
        "pasted_within_s_of_return": None, "app_switches": 0, "away_s": 0.0,
        "pay_screen_s": 25.0, "abandoned_flows_30m": 0}
# Someone who always types slowly: slow, but no slower than their own normal.
SLOW_TYPIST = {**CALM, "amount_median_gap_s": 2.6, "amount_max_gap_s": 5.0, "amount_gap_vs_usual": 1.1}
CALL_ONLY = {"call": {"active": True, "kind": "sim", "caller_number": UNKNOWN_CALLER,
                      "caller_in_contacts": False, "started_min_ago": 12}, "lures": []}
EXAMPLES = Path(__file__).resolve().parents[2] / "contracts" / "examples"


def ctx(session, call=None, speaker=None):
    c = {"lures": [], "session": session}
    if call:
        c["call"] = {**call["call"], "speaker_on": speaker}
    return c


def other_person(world, n=1):
    """An ordinary person's UPI ID: an unknown payee with nothing mule-like about it."""
    return world[1]["users"].set_index("user_id").loc[users_in(world)[n], "upi_id"]


# ---------- the signs themselves ----------

def test_signs_from_the_coached_example():
    s = SessionSignal(**COACHED)
    assert dictated(s) and pasted_after_switch(s) and hesitation(s)


def test_slow_typist_is_compared_with_their_own_speed():
    assert dictated(SessionSignal(**SLOW_TYPIST)) is False


def test_no_baseline_needs_slow_and_broken_rhythm():
    new_user = {**COACHED, "amount_gap_vs_usual": None}
    assert dictated(SessionSignal(**new_user)) is True
    steady_slow = {**new_user, "amount_median_gap_s": 2.2, "amount_max_gap_s": 2.8}
    assert dictated(SessionSignal(**steady_slow)) is False


def test_unknown_stays_unknown():
    assert session_features(None) == {k: None for k in session_features(None)}
    blank = session_features(SessionSignal())
    assert blank["session_dictated"] is None and blank["session_pasted_after_switch"] is None
    assert dictated(SessionSignal(amount_digits=2)) is False  # too short to judge, not "unknown"


def test_paste_without_leaving_the_app_is_not_after_a_switch():
    s = SessionSignal(payee_pasted=True, pasted_within_s_of_return=None, app_switches=0)
    assert pasted_after_switch(s) is False
    assert pasted_after_switch(SessionSignal(payee_pasted=True, pasted_within_s_of_return=95)) is False


# ---------- through the engine ----------

def test_coached_payment_to_the_mule_is_paused(engine, mock, world):
    pump(mock[1], world)
    r = engine.post("/v1/decide", json=req(context=ctx(COACHED, CALL_ONLY, speaker=True))).json()
    assert r["tier"] in ("T3", "T4")
    assert "R12_coached_session" in r["reasons"] and "R1_live_unknown_call" in r["reasons"]
    assert r["playbook"] == "digital_arrest"


def test_coaching_adds_the_second_family_when_the_payee_looks_clean(engine, world):
    """Unknown caller + a clean-looking payee: the call alone is one family (T0). Being talked
    through the Pay screen is a second, independent family, so RUKO now adds care."""
    payee = other_person(world)
    (calm_user, coached_user) = users_in(world)[3:5]  # two people, so one payment doesn't count as the other's earlier try
    def pay(user, session, rid):
        amount = baseline(world, user).median_90d or 1_000
        return engine.post("/v1/decide", json=req(user=user, payee=payee, amount=amount,
                                                  context=ctx(session, CALL_ONLY), rid=rid)).json()
    before, after = pay(calm_user, CALM, "r_a"), pay(coached_user, COACHED, "r_b")
    assert before["tier"] == "T0"
    assert after["tier"] >= "T1" and "R12_coached_session" in after["reasons"]
    assert "R7_tranche_pattern" not in after["reasons"]


def test_coached_session_alone_never_interrupts(engine, world):
    """Rule 5: behaviour is one family. No call, a known payee, a usual amount -> at most T1."""
    for i, user in enumerate(users_in(world)[:5]):
        base = baseline(world, user)
        payee = next(iter(base.known_payees), other_person(world, 2))
        r = engine.post("/v1/decide", json=req(user=user, payee=payee, amount=base.median_90d or 500,
                                               context=ctx(COACHED), rid=f"r_alone_{i}")).json()
        assert r["tier"] in ("T0", "T1"), (user, r)


def test_slow_typist_on_an_unknown_call_gets_no_coaching_reason(engine, world):
    user, payee = users_in(world)[0], other_person(world)
    r = engine.post("/v1/decide", json=req(user=user, payee=payee, amount=900,
                                           context=ctx(SLOW_TYPIST, CALL_ONLY))).json()
    assert "R12_coached_session" not in r["reasons"]


def test_session_null_changes_nothing(engine, mock, world):
    pump(mock[1], world)
    a = engine.post("/v1/decide", json=req(context=MEENA_CONTEXT, rid="r_x")).json()
    b = engine.post("/v1/decide", json=req(context={**MEENA_CONTEXT, "session": None}, rid="r_y")).json()
    assert a["tier"] == b["tier"] and a["reasons"] == b["reasons"]


def test_speaker_without_a_call_means_nothing(engine, world):
    user, payee = users_in(world)[0], other_person(world)
    c = {"call": {"active": False, "speaker_on": True}, "lures": []}
    r = engine.post("/v1/decide", json=req(user=user, payee=payee, amount=900, context=c)).json()
    assert r["tier"] == "T0"


def test_older_contract_requests_still_validate():
    body = json.loads((EXAMPLES / "decide_request_meena.json").read_text(encoding="utf-8"))
    assert "session" not in body["context"]
    DecideRequest.model_validate(body)
    DecideRequest.model_validate(json.loads((EXAMPLES / "decide_request_coached.json").read_text(encoding="utf-8")))
