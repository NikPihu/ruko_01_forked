"""c2-0.8: alert feedback, watch events, the app's own payments, alert health."""
import json
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

import api.main
from api.main import create_app as create_engine
from schema.events import MyPayments
from test_decide import (DEMO_KIRANA_UPI, DEMO_MEENA, DEMO_MULE_UPI, MEENA_CONTEXT, NOW, mock, pump, req,  # noqa: F401
                         users_in, world)


@pytest.fixture()
def engine(world, mock, monkeypatch):
    monkeypatch.setattr(api.main, "DEADLINE_S", 10.0)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock[0]), base_url="http://mock")
    return TestClient(create_engine(world[0], intel_client=client, intel_cache_ttl_s=0, log_path=None,
                                    evidence_async=False, intel_budget_s=5.0))


def fb(rid, user, action, fid="f_1", why=None, dwell=5000, ts=NOW):
    return {"feedback_id": fid, "request_id": rid, "user_id": user, "action": action, "why": why,
            "dwell_ms": dwell, "ts": (ts + timedelta(minutes=1)).isoformat()}


def friend_of(world, user):
    users = world[1]["users"].set_index("user_id")
    return users.loc[[u for u in users_in(world) if u != user][3], "upi_id"]


# ---------- feedback ----------

def test_feedback_is_recorded_for_the_users_own_payment(engine, world):
    user = users_in(world)[0]
    engine.post("/v1/decide", json=req(user=user, payee=DEMO_KIRANA_UPI, amount=180, entry="qr", rid="p_1"))
    r = engine.post("/v1/feedback", json=fb("p_1", user, "tip_seen")).json()
    assert r["recorded"] is True and r["trusted_accepted"] is None
    assert engine.get("/v1/transactions/p_1").json()["feedback"][0]["action"] == "tip_seen"


def test_feedback_for_someone_elses_or_unknown_payment_is_refused(engine, world):
    a, b = users_in(world)[:2]
    engine.post("/v1/decide", json=req(user=a, payee=DEMO_KIRANA_UPI, amount=180, entry="qr", rid="p_a"))
    assert engine.post("/v1/feedback", json=fb("p_a", b, "tip_seen")).json()["recorded"] is False
    assert engine.post("/v1/feedback", json=fb("nope", a, "tip_seen", fid="f_2")).json()["recorded"] is False


def test_a_retried_feedback_counts_once(engine, world):
    user = users_in(world)[0]
    engine.post("/v1/decide", json=req(user=user, payee=DEMO_KIRANA_UPI, amount=180, entry="qr", rid="p_1"))
    for _ in range(3):
        engine.post("/v1/feedback", json=fb("p_1", user, "waited"))
    assert len(engine.get("/v1/transactions/p_1").json()["feedback"]) == 1


def test_daily_feedback_limit(engine, world):
    user = users_in(world)[0]
    engine.post("/v1/decide", json=req(user=user, payee=DEMO_KIRANA_UPI, amount=180, entry="qr", rid="p_1"))
    answers = [engine.post("/v1/feedback", json=fb("p_1", user, "tip_seen", fid=f"f_{i}")).json()["recorded"]
               for i in range(31)]
    assert answers[:30] == [True] * 30 and answers[30] is False


def test_i_know_them_refused_when_someone_controls_the_phone(engine, mock, world):
    """Meena's mule, with remote control on: coached victims tap "I know them" too."""
    pump(mock[1], world)
    r = engine.post("/v1/decide", json=req(context=MEENA_CONTEXT, says="government", rid="p_m")).json()
    assert r["tier"] in ("T3", "T4")
    ans = engine.post("/v1/feedback", json=fb("p_m", DEMO_MEENA, "i_know_them", why="family")).json()
    assert ans["recorded"] and ans["trusted_accepted"] is False and ans["message_key"] == "know_them_not_accepted"
    again = engine.post("/v1/decide", json=req(context=MEENA_CONTEXT, says="government", rid="p_m2",
                                               ts=NOW + timedelta(minutes=5))).json()
    assert again["tier"] in ("T3", "T4")


def test_i_know_them_accepted_for_a_clean_payee(engine, world):
    user = users_in(world)[0]
    friend = friend_of(world, user)
    engine.post("/v1/decide", json=req(user=user, payee=friend, amount=900, rid="p_f"))
    ans = engine.post("/v1/feedback", json=fb("p_f", user, "i_know_them", why="friend")).json()
    assert ans["trusted_accepted"] is True
    assert friend in engine.app.state.trusted[user]


# ---------- watch events ----------

def test_watch_events_move_the_stage_before_any_payment(engine, world):
    user = users_in(world)[0]
    w = lambda eid, kind, **kw: engine.post("/v1/watch", json={  # noqa: E731
        "event_id": eid, "user_id": user, "kind": kind, "ts": NOW.isoformat(), **kw}).json()
    assert w("w1", "lure_seen", lure_tag="arrest_threat", lure_conf=0.9, source="notification")["stage"] == "S1"
    assert w("w2", "long_unknown_call", call_kind="voip", call_minutes=20)["stage"] == "S2"
    assert w("w3", "remote_access_on")["stage"] == "S3"
    assert w("w3", "remote_access_on")["recorded"] is False        # a repeat is ignored
    r = engine.post("/v1/decide", json=req(user=user, payee=friend_of(world, user), amount=900, rid="p_w",
                                           ts=NOW + timedelta(minutes=10))).json()
    assert r["stage"] in ("S4", "S5")
    path = [s for s, _ in engine.get("/v1/transactions/p_w").json()["details"]["stage_path"]]
    assert "S3" in path
    kinds = [e["kind"] for e in engine.get(f"/v1/users/{_hash(user)}/timeline").json()["events"]]
    assert kinds.count("watch") == 3


def test_a_weak_lure_does_not_count(engine, world):
    user = users_in(world)[0]
    r = engine.post("/v1/watch", json={"event_id": "w", "user_id": user, "kind": "lure_seen", "ts": NOW.isoformat(),
                                       "lure_tag": "kyc", "lure_conf": 0.3}).json()
    assert r["stage"] == "S0"


def test_voip_call_with_unknown_caller_counts_as_contact(engine, world):
    """The phone can't know who is on a WhatsApp call: unknown is not safe."""
    user = users_in(world)[0]
    ctx = {"call": {"active": True, "kind": "voip", "caller_in_contacts": None, "started_min_ago": 20}, "lures": []}
    r = engine.post("/v1/decide", json=req(user=user, payee=friend_of(world, user), amount=900, context=ctx)).json()
    feats = engine.get(f"/v1/transactions/{r['request_id']}").json()["details"]["features"]
    assert feats["minutes_since_first_contact"] is not None   # the call counted as first contact


# ---------- the app's own payments, alert health ----------

def test_my_payments_are_mine_and_have_no_scores(engine, mock, world):
    pump(mock[1], world)
    engine.post("/v1/decide", json=req(context=MEENA_CONTEXT, says="government", rid="p_m"))
    other = users_in(world)[0]
    engine.post("/v1/decide", json=req(user=other, payee=DEMO_KIRANA_UPI, amount=180, entry="qr", rid="p_o"))
    body = engine.get("/v1/me/payments", params={"user_id": DEMO_MEENA}).json()
    MyPayments.model_validate(body)
    assert [p["payment_id"] for p in body["payments"]] == ["p_m"]
    assert "p_scam" not in json.dumps(body) and "family" not in json.dumps(body)


def test_alert_health_counts_actions(engine, mock, world):
    pump(mock[1], world)
    engine.post("/v1/decide", json=req(context=MEENA_CONTEXT, says="government", rid="p_m"))
    engine.post("/v1/feedback", json=fb("p_m", DEMO_MEENA, "waited", dwell=40_000))
    engine.post("/v1/payment/outcome", json={"request_id": "p_m", "user_id": DEMO_MEENA, "payee_upi_id": DEMO_MULE_UPI,
                                             "amount_inr": 95_000, "status": "cancelled",
                                             "ts": (NOW + timedelta(minutes=2)).isoformat()})
    h = engine.get("/v1/metrics/alerts").json()
    tier = next(t for t, v in h["tiers"].items() if v["shown"])
    assert h["tiers"][tier]["cancelled_share"] == 1.0 and h["tiers"][tier]["median_dwell_ms"] == 40_000
    assert h["actions"] == {"waited": 1} and h["interruptions_per_1000_checks"] == 1000.0


def _hash(user):
    from evidence.store import pseudonym
    return pseudonym(user)


def test_i_know_them_refused_for_a_mule_like_payee_without_remote_control(engine, mock, world):
    """Coached on a call, no screen control, mule not listed yet: the payee itself looks like a mule."""
    pump(mock[1], world)
    ctx = {"call": {"active": True, "kind": "voip", "caller_in_contacts": False, "started_min_ago": 30},
           "lures": [], "session": {"amount_digits": 5, "amount_gap_vs_usual": 4.8, "payee_pasted": True,
                                    "pasted_within_s_of_return": 6.0, "app_switches": 3}}
    engine.post("/v1/decide", json=req(context=ctx, rid="p_c"))
    ans = engine.post("/v1/feedback", json=fb("p_c", DEMO_MEENA, "i_know_them", why="family")).json()
    assert ans["trusted_accepted"] is False and ans["message_key"] == "know_them_not_accepted"


# ---------- A1: video call while paying; A5: AI-written lures (c2-0.10) ----------

def test_video_call_with_unknown_caller_makes_it_digital_arrest(engine, mock, world):
    import json as _json
    from pathlib import Path
    pump(mock[1], world)
    body = _json.loads((Path(__file__).resolve().parents[2] / "contracts/examples/decide_request_video_call.json")
                       .read_text(encoding="utf-8"))
    body["ts"] = NOW.isoformat()
    r = engine.post("/v1/decide", json=body).json()
    assert r["tier"] in ("T3", "T4") and r["playbook"] == "digital_arrest"
    assert "R1_live_unknown_call" in r["reasons"]
    feats = engine.get(f"/v1/transactions/{r['request_id']}").json()["details"]["features"]
    assert feats["video_call"] is True


def test_video_call_alone_never_interrupts(engine, world):
    user = users_in(world)[0]
    ctx = {"call": {"active": True, "kind": "voip", "caller_in_contacts": None, "started_min_ago": 5, "video": True},
           "lures": []}
    r = engine.post("/v1/decide", json=req(user=user, payee=DEMO_KIRANA_UPI, amount=180, entry="qr", context=ctx)).json()
    assert r["tier"] in ("T0", "T1")


def test_ai_written_lures_are_counted(engine, world):
    user = users_in(world)[0]
    for i, ai in enumerate([True, True, False]):
        engine.post("/v1/watch", json={"event_id": f"l{i}", "user_id": user, "kind": "lure_seen", "ts": NOW.isoformat(),
                                       "lure_tag": "kyc", "lure_conf": 0.9, "source": "sms", "ai_written": ai})
    assert engine.get("/v1/metrics/alerts").json()["lures"] == {"lures_seen": 3, "ai_written": 2}


def test_watch_thresholds_come_from_the_shared_rules_file():
    """Phone and server read the same early-warning numbers (rule 6): contracts/watch_rules.json."""
    import json
    from pathlib import Path

    from features import tracker

    rules = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "watch_rules.json").read_text(encoding="utf-8"))
    assert tracker.LONG_CALL_MIN == rules["long_call_min"]
    assert tracker.LURE_MIN_CONF == rules["lure_min_conf"]
    app_copy = Path(__file__).resolve().parents[2] / "android" / "ruko-sdk" / "src" / "main" / "assets" / "watch_rules.json"
    assert json.loads(app_copy.read_text(encoding="utf-8")) == rules


def test_alert_health_counts_early_warnings_by_kind():
    """The console's Alert health card shows which early warnings phones sent (by kind)."""
    from datetime import datetime, timezone

    from store.db import TxnStore

    s = TxnStore()
    now = datetime.now(timezone.utc).isoformat()
    for i, kind in enumerate(["lure_seen", "lure_seen", "long_unknown_call"]):
        s.record_watch(f"e{i}", "u_demo", kind, {"ai_written": True} if i == 0 else {}, now)
    assert s.watch_counts() == {"lure_seen": 2, "long_unknown_call": 1}
