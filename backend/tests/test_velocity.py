"""#3 New and spreading: an account RUKO first saw recently that several users already pay (a fresh
AI-crew mule, before any registry lists it). Crowd numbers come from policy.yaml (rule 6); the
evidence counts with any scorer via the overlay (api/overlay.py) but never interrupts alone (rule 5)."""
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

import api.main
from api import overlay
from api.main import create_app as create_engine
from api.policy import Policy
from graph import store as graph_store
from graph.store import GraphStore
from test_decide import DEMO_KIRANA_UPI, LURE, NOW, mock, req, users_in, world  # noqa: F401

FRESH = "fresh.crew.mule@ybl"   # not in the simulated world: no bank or registry knows it


@pytest.fixture()
def engine(world, mock, monkeypatch):
    monkeypatch.setattr(api.main, "DEADLINE_S", 10.0)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock[0]), base_url="http://mock")
    return TestClient(create_engine(world[0], intel_client=client, intel_cache_ttl_s=0, log_path=None,
                                    evidence_async=False, intel_budget_s=5.0))


def test_crowd_thresholds_come_from_policy_yaml():
    """Rule 6: the crowd numbers live in policy.yaml, not in code."""
    cfg = yaml.safe_load((Path(api.main.__file__).with_name("policy.yaml")).read_text())["crowd"]
    assert graph_store.CROWD_BAIT_USERS == cfg["bait_users"]
    assert graph_store.CROWD_EPISODE_USERS == cfg["episode_users"]
    assert graph_store.CROWD_FANIN_6H == cfg["fanin_6h"]
    assert graph_store.NEW_USER_WEIGHT == cfg["new_user_weight"]
    assert graph_store.CROWD["new_account_min_users"] == cfg["new_account_min_users"]


def test_new_account_paid_by_several_users_is_new_and_spreading():
    g = GraphStore()
    for i in range(2):
        g.add_payment(f"u{i}", FRESH, 2_000, NOW + timedelta(minutes=10 * i))
    assert not g.account_signals(FRESH, NOW + timedelta(minutes=30))["new_and_spreading"]  # 2 users: not yet
    g.add_payment("u2", FRESH, 2_000, NOW + timedelta(minutes=40))
    sig = g.account_signals(FRESH, NOW + timedelta(minutes=40))
    assert sig["new_and_spreading"] and sig["ruko_payers"] == 3 and sig["first_seen_hours"] < 1


def test_an_account_ruko_has_known_for_days_is_not_new():
    g = GraphStore()
    g.add_payment("u_old", FRESH, 500, NOW - timedelta(days=3))
    for i in range(3):
        g.add_payment(f"u{i}", FRESH, 2_000, NOW + timedelta(minutes=i))
    assert not g.account_signals(FRESH, NOW + timedelta(minutes=5))["new_and_spreading"]


def _policy(families, p_scam, **feat):
    f = {"amount_inr": 5_000, "trusted_payee": False, "payee_registry_listed": False,
         "caller_registry_listed": False, "payee_fri_level": None, "caller_fri_level": None,
         "payee_approved_suspect": False, "payee_micro_anchor": False, **feat}
    pol = Policy()
    s = overlay.apply({"p_scam": p_scam, "family_scores": families, "reasons": ["R5_lure_message"],
                       "playbook": None}, f, pol.cfg)
    return s, pol.decide(s, f, "S1", False, "u", NOW)


def test_overlay_counts_with_a_model_that_never_learned_the_feature():
    """The trained model scored the payee family low (it has no such input); the overlay lifts it, and
    with the user's own scam message (L) the two families raise the payment to a warning."""
    s, d = _policy({"C": 0.0, "L": 0.7, "P": 0.1, "B": 0.2}, p_scam=0.2, payee_new_and_spreading=True)
    assert s["family_scores"]["P"] >= 0.6 and s["reasons"][0] == "R3_mule_like_payee"
    assert d.tier == "T2" and "evidence_overlay" in d.applied


def test_overlay_alone_never_interrupts():
    """Rule 5: new-and-spreading is one family (P); with nothing else lit it stays silent."""
    _, d = _policy({"C": 0.0, "L": 0.0, "P": 0.1, "B": 0.0}, p_scam=0.2, payee_new_and_spreading=True)
    assert d.tier == "T0" and "evidence_overlay" not in d.applied
    # Unknown (None) is never evidence either way.
    s, _ = _policy({"C": 0.0, "L": 0.7, "P": 0.1, "B": 0.2}, p_scam=0.2, payee_new_and_spreading=None)
    assert "overlay" not in s


def test_fresh_mule_paid_by_three_users_is_flagged(engine, world):
    users = users_in(world)[2:5]
    for i, u in enumerate(users[:2]):
        engine.post("/v1/decide", json=req(user=u, payee=FRESH, amount=3_000, entry="typed",
                                           rid=f"nv_{i}", ts=NOW + timedelta(minutes=5 * i)))
    third = engine.post("/v1/decide", json=req(user=users[2], payee=FRESH, amount=3_000, entry="typed",
                                                context={"lures": LURE}, rid="nv_2",
                                                ts=NOW + timedelta(minutes=12))).json()
    feats = engine.get(f"/v1/evidence/{third['evidence_id']}").json()["features"]
    assert feats["payee_new_and_spreading"] is True
    assert third["tier"] in ("T2", "T3", "T4") and "R3_mule_like_payee" in third["reasons"]


def test_a_busy_verified_shop_is_never_new_and_spreading(engine, world):
    """A verified merchant (or an account the bank says is old) many users pay is not a fresh mule."""
    users = users_in(world)[6:9]
    last = {}
    for i, u in enumerate(users):
        last = engine.post("/v1/decide", json=req(user=u, payee=DEMO_KIRANA_UPI, amount=150, entry="qr",
                                                  context={"lures": LURE}, rid=f"kv_{i}",
                                                  ts=NOW + timedelta(minutes=i))).json()
    if last["evidence_id"]:
        assert engine.get(f"/v1/evidence/{last['evidence_id']}").json()["features"]["payee_new_and_spreading"] is False
    assert "R3_mule_like_payee" not in last["reasons"]
