"""c2-0.15: one unknown number calling many RUKO users (AI voice at scale, R14), and an OTP that
arrives during an unknown call (account takeover, R15)."""
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import api.main
from api import overlay
from api.main import create_app as create_engine
from api.policy import Policy
from features import tracker as tracker_mod
from features.tracker import StageTracker
from graph.campaigns import CampaignStore, wire_value
from schema.events import WatchEvent
from test_decide import NOW, mock, req, users_in, world  # noqa: F401

NUMBER = "+91 98123 45670"
CALLER = wire_value("phone", NUMBER)
PAYEE = "help.desk.refund@ybl"   # not in the simulated world: no bank or registry knows it


@pytest.fixture()
def engine(world, mock, monkeypatch):
    monkeypatch.setattr(api.main, "DEADLINE_S", 10.0)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock[0]), base_url="http://mock")
    return TestClient(create_engine(world[0], intel_client=client, intel_cache_ttl_s=0, log_path=None,
                                    evidence_async=False, intel_budget_s=5.0))


def _watch(engine, user, kind, minutes=0, caller=CALLER, **kw):
    body = {"event_id": f"w_{user}_{kind}_{minutes}", "user_id": user, "kind": kind,
            "ts": (NOW + timedelta(minutes=minutes)).isoformat(), "call_kind": "sim", "caller_hash": caller, **kw}
    return engine.post("/v1/watch", json=body).json()


def _features(engine, rid):
    return engine.get(f"/v1/transactions/{rid}").json()["details"]["features"]


def _call(minutes_on=6, number="9812345670", known=False):
    return {"active": True, "kind": "sim", "caller_number": number, "caller_in_contacts": known,
            "started_min_ago": minutes_on}


# ---------- the store ----------

def test_a_number_calling_many_counts_different_users_only():
    st = CampaignStore(caller_window_hours=24, caller_min_users=3)
    for i in range(4):                                  # one person called four times
        st.record_call("u0", CALLER, NOW + timedelta(minutes=i))
    assert st.caller_users(CALLER, NOW + timedelta(minutes=5)) == 1 and st.calling_many(CALLER, NOW) is False
    st.record_call("u1", CALLER, NOW + timedelta(hours=1))
    st.record_call("u2", CALLER, NOW + timedelta(hours=2))
    assert st.calling_many(CALLER, NOW + timedelta(hours=2)) is True
    assert st.calling_many(CALLER, NOW + timedelta(hours=26)) is False   # out of the 24 h window
    assert st.calling_many(None, NOW) is None                            # unknown number: unknown (rule 1)
    assert st.record_call("u3", "+919812345670", NOW) is False           # a raw number is never kept
    st.expire(NOW + timedelta(hours=27))
    assert not st.calls


def test_callers_show_on_spreading_now_without_the_number():
    st = CampaignStore()
    for i in range(3):
        st.record_call(f"u{i}", CALLER, NOW)
    [row] = [t for t in st.top(NOW) if t["kind"] == "caller"]
    assert row["value"] is None and row["users"] == 3 and row["spreading"]


def test_the_watch_event_takes_only_a_pseudonym():
    ok = {"event_id": "e", "user_id": "u", "kind": "otp_during_call", "ts": NOW.isoformat(), "caller_hash": CALLER,
          "otp_purpose": "bank"}
    assert WatchEvent.model_validate(ok).caller_hash == CALLER
    for bad in ("+919812345670", "9812345670", "sha256:xyz"):
        with pytest.raises(ValidationError):   # rule 7: never a raw number
            WatchEvent.model_validate({**ok, "caller_hash": bad})
    with pytest.raises(ValidationError):       # rule 2: never the code or the text
        WatchEvent.model_validate({**ok, "otp": "482915"})


def test_only_an_otp_for_upi_or_a_bank_is_reported():
    """The phone works out what the OTP is for; the server takes only UPI and bank ones."""
    base = {"event_id": "e", "user_id": "u", "kind": "otp_during_call", "ts": NOW.isoformat()}
    for purpose in ("upi", "bank"):
        assert WatchEvent.model_validate({**base, "otp_purpose": purpose}).otp_purpose == purpose
    for bad in ({}, {"otp_purpose": "other"}, {"otp_purpose": "unknown"}, {"otp_purpose": None}):
        with pytest.raises(ValidationError):
            WatchEvent.model_validate({**base, **bad})
    with pytest.raises(ValidationError):   # only on otp_during_call
        WatchEvent.model_validate({**base, "kind": "long_unknown_call", "otp_purpose": "bank"})


def test_a_non_money_otp_is_refused_by_the_api(engine, world):
    user = users_in(world)[0]
    r = engine.post("/v1/watch", json={"event_id": "x", "user_id": user, "kind": "otp_during_call",
                                       "ts": NOW.isoformat(), "otp_purpose": "other"})
    assert r.status_code == 422


# ---------- the stage tracker ----------

def test_an_otp_on_an_unknown_call_is_control_and_is_remembered_for_a_while():
    t = StageTracker()
    assert t.observe("u", "otp_during_call", NOW) == "S3"
    s = t.sessions["u"]
    assert s.otp_ts == NOW and s.contacts
    later = tracker_mod.OTP_MEMORY + timedelta(minutes=1)
    t2 = StageTracker()
    t2.observe("u", "otp_during_call", NOW)
    from schema.events import DecideRequest
    r = DecideRequest.model_validate(req(user="u", payee=PAYEE, amount=5_000, ts=NOW + timedelta(minutes=10)))
    assert t2.update(r, new_payee=True).otp_on_call is True
    r = DecideRequest.model_validate(req(user="u", payee=PAYEE, amount=5_000, ts=NOW + later, rid="r2"))
    assert t2.update(r, new_payee=True).otp_on_call is None             # forgotten: unknown, never False


# ---------- wired into the engine ----------

def test_a_number_that_called_three_users_is_call_evidence_r14(engine, world):
    users = users_in(world)
    for i in range(3):
        assert _watch(engine, users[i], "long_unknown_call", minutes=i, call_minutes=9)["recorded"]
    r = engine.post("/v1/decide", json=req(user=users[3], payee=PAYEE, amount=40_000, entry="typed",
                                           context={"call": _call(), "lures": []}, rid="cc_1",
                                           ts=NOW + timedelta(minutes=30))).json()
    feats = _features(engine, "cc_1")
    assert feats["caller_many_users"] is True
    assert r["tier"] in ("T2", "T3", "T4") and "R14_caller_many_users" in r["reasons"]


def test_the_crowd_also_grows_from_payments_made_on_the_call(engine, world):
    users = users_in(world)
    for i in range(2):
        engine.post("/v1/decide", json=req(user=users[i], payee="kiran.p@oksbi", amount=500,
                                           context={"call": _call(), "lures": []}, rid=f"p_{i}",
                                           ts=NOW + timedelta(minutes=i)))
    engine.post("/v1/decide", json=req(user=users[2], payee=PAYEE, amount=500, context={"call": _call(), "lures": []},
                                       rid="p_2", ts=NOW + timedelta(minutes=3)))
    assert _features(engine, "p_2")["caller_many_users"] is True
    # A contact's number never counts, and no number is unknown (rule 1).
    engine.post("/v1/decide", json=req(user=users[3], payee=PAYEE, amount=500,
                                       context={"call": {"active": True, "kind": "voip", "started_min_ago": 3}, "lures": []},
                                       rid="p_3", ts=NOW + timedelta(minutes=4)))
    assert _features(engine, "p_3")["caller_many_users"] is None


def test_one_user_called_many_times_is_not_a_crowd(engine, world):
    user = users_in(world)[0]
    for i in range(4):
        _watch(engine, user, "long_unknown_call", minutes=i, call_minutes=6)
    engine.post("/v1/decide", json=req(user=users_in(world)[1], payee=PAYEE, amount=900,
                                       context={"call": _call(), "lures": []}, rid="one", ts=NOW + timedelta(minutes=10)))
    assert _features(engine, "one")["caller_many_users"] is False


def test_an_otp_on_an_unknown_call_then_a_payment_is_named_otp_takeover_r15(engine, world):
    user = users_in(world)[0]
    w = _watch(engine, user, "otp_during_call", otp_purpose="upi")
    assert w["recorded"] and w["stage"] == "S3"
    r = engine.post("/v1/decide", json=req(user=user, payee=PAYEE, amount=25_000, entry="typed",
                                           context={"lures": []}, rid="otp_1",
                                           ts=NOW + timedelta(minutes=8))).json()
    assert _features(engine, "otp_1")["otp_on_call"] is True
    assert r["tier"] in ("T2", "T3", "T4") and "R15_otp_on_call" in r["reasons"]
    assert r["playbook"] == "otp_takeover" and r["message_key"].endswith("_otp_takeover")
    # The watch record keeps the pseudonym, never a number.
    rows = engine.get(f"/v1/users/{_hash(user)}/timeline").json()
    assert "9812345670" not in str(rows)


def _hash(user):
    from evidence.store import pseudonym
    return pseudonym(user)


def test_call_evidence_alone_never_interrupts():
    """Rule 5: both new signs are about the call, so together they still light one family."""
    pol = Policy()
    f = {"amount_inr": 5_000, "trusted_payee": False, "payee_registry_listed": False,
         "caller_registry_listed": False, "payee_fri_level": None, "caller_fri_level": None,
         "payee_approved_suspect": False, "payee_micro_anchor": False,
         "caller_many_users": True, "otp_on_call": True}
    s = overlay.apply({"p_scam": 0.2, "family_scores": {"C": 0.1, "L": 0.0, "P": 0.1, "B": 0.0},
                       "reasons": [], "playbook": None}, f, pol.cfg)
    assert s["family_scores"]["C"] >= 0.6 and s["reasons"][:2] == ["R15_otp_on_call", "R14_caller_many_users"]
    assert pol.decide(s, f, "S3", True, "u", NOW).tier == "T0"


def test_numbers_come_from_config():
    import yaml
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    cfg = yaml.safe_load((root / "backend" / "api" / "policy.yaml").read_text())["campaign"]
    st = CampaignStore()
    assert st.caller_min_users == cfg["caller_min_users"] and st.caller_window == timedelta(hours=cfg["caller_window_hours"])
    import json
    rules = json.loads((root / "contracts" / "watch_rules.json").read_text(encoding="utf-8"))
    assert tracker_mod.OTP_MEMORY == timedelta(minutes=rules["otp_recent_min"])
