"""#1 Same scam, many phones: money handles counted across distinct users (graph/campaigns.py)."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from graph import campaigns
from graph.campaigns import CampaignStore, hashed, normalise, wire_value

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
MULE = "secure.settlement.desk@okaxis"


def test_normalisation_matches_the_shared_vectors():
    """The phone hashes exactly like the server: both are checked against these vectors."""
    vec = json.loads((ROOT / "contracts" / "examples" / "handle_vectors.json").read_text(encoding="utf-8"))
    assert vec["salt"] == campaigns.SALT
    for v in vec["vectors"]:
        assert normalise(v["kind"], v["raw"]) == v["normalised"], v
        assert wire_value(v["kind"], v["raw"]) == v["wire"], v


def test_links_and_numbers_are_hashed_upi_ids_stay_plain():
    """Rule 2 / rule 7: the UPI ID is plain like any payee; link hosts and numbers are pseudonyms."""
    assert wire_value("upi", " Secure.Settlement.Desk@OKAXIS ") == MULE
    number = wire_value("phone", "+91 98123 45670")
    link = wire_value("link", "https://www.kyc-update-now.example/verify")
    for w in (number, link):
        assert w.startswith("sha256:") and "9812345670" not in w and "kyc" not in w
    # Every way of writing the same number becomes the same pseudonym.
    assert number == wire_value("phone", "098123-45670") == wire_value("phone", "9812345670")
    assert hashed("phone", "+919812345670", salt="other") != number


def test_a_handle_spreads_only_across_different_users():
    st = CampaignStore(window_minutes=60, min_users=3)
    for i in range(5):                                   # one phone getting the same scam five times
        st.record("u0", [("upi", MULE)], NOW + timedelta(minutes=i))
    assert st.users("upi", MULE, NOW + timedelta(minutes=5)) == 1 and not st.spreading("upi", MULE, NOW + timedelta(minutes=5))
    st.record("u1", [("upi", MULE)], NOW + timedelta(minutes=6))
    st.record("u2", [("upi", MULE.upper())], NOW + timedelta(minutes=7))
    assert st.spreading("upi", MULE, NOW + timedelta(minutes=8))


def test_old_sightings_drop_out_of_the_window_and_expire():
    st = CampaignStore(window_minutes=60, min_users=3, keep_hours=24)
    for i in range(3):
        st.record(f"u{i}", [("upi", MULE)], NOW)
    assert st.spreading("upi", MULE, NOW + timedelta(minutes=30))
    assert not st.spreading("upi", MULE, NOW + timedelta(minutes=61))   # outside the window
    st.expire(NOW + timedelta(hours=25))
    assert st.users("upi", MULE, NOW + timedelta(hours=25)) == 0 and not st.seen


def test_spreading_now_hides_hashed_handles():
    st = CampaignStore(window_minutes=60, min_users=3)
    number = wire_value("phone", "9812345670")
    for i in range(3):
        st.record(f"u{i}", [("upi", MULE), ("phone", number)], NOW)
    top = {t["kind"]: t for t in st.top(NOW)}
    assert top["upi"]["value"] == MULE and top["upi"]["users"] == 3 and top["upi"]["spreading"]
    assert top["phone"]["value"] is None and top["phone"]["users"] == 3


def test_campaign_numbers_come_from_policy_yaml():
    cfg = yaml.safe_load((ROOT / "backend" / "api" / "policy.yaml").read_text())["campaign"]
    assert campaigns.CAMPAIGN["min_users"] == cfg["min_users"] == CampaignStore().min_users
    assert CampaignStore().window == timedelta(minutes=cfg["window_minutes"])


# ---------- wired into the engine (c2-0.13) ----------

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import api.main  # noqa: E402
from api import overlay  # noqa: E402
from api.main import create_app as create_engine  # noqa: E402
from api.policy import Policy  # noqa: E402
from test_decide import LURE, NOW as SIM_NOW, mock, req, users_in, world  # noqa: E402,F401

CAMPAIGN_UPI = "kyc.refund.desk@ybl"   # not in the simulated world: no bank or registry knows it
CALLBACK = "+91 98123 45670"


@pytest.fixture()
def engine(world, mock, monkeypatch):
    monkeypatch.setattr(api.main, "DEADLINE_S", 10.0)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock[0]), base_url="http://mock")
    return TestClient(create_engine(world[0], intel_client=client, intel_cache_ttl_s=0, log_path=None,
                                    evidence_async=False, intel_budget_s=5.0))


def _watch(engine, user, i, handles, tag="kyc", minutes=0):
    return engine.post("/v1/watch", json={
        "event_id": f"w_{user}_{i}", "user_id": user, "kind": "lure_seen", "source": "sms",
        "ts": (SIM_NOW + timedelta(minutes=minutes)).isoformat(), "lure_tag": tag, "lure_conf": 0.9,
        "handles": handles}).json()


def _spread(engine, n=3, upi=CAMPAIGN_UPI, phone=None):
    """n different phones each got a differently worded scam message carrying the same handles."""
    handles = [{"kind": "upi", "value": wire_value("upi", upi)}]
    if phone:
        handles.append({"kind": "phone", "value": wire_value("phone", phone)})
    for i, tag in zip(range(n), ("kyc", "refund", "arrest_threat", "task_job")):
        assert _watch(engine, f"u_phone{i}", i, handles, tag=tag, minutes=i)["recorded"]


def test_a_spreading_upi_id_gets_r13_when_the_payer_also_got_the_scam(engine, world):
    _spread(engine)
    user = users_in(world)[3]
    r = engine.post("/v1/decide", json=req(user=user, payee=CAMPAIGN_UPI, amount=4_000, entry="typed",
                                           context={"lures": LURE}, rid="c_1",
                                           ts=SIM_NOW + timedelta(minutes=10))).json()
    feats = engine.get(f"/v1/evidence/{r['evidence_id']}").json()["features"]
    assert feats["payee_in_campaign"] is True
    assert r["tier"] in ("T2", "T3", "T4") and "R13_scam_campaign" in r["reasons"]


def test_one_phone_alone_never_makes_a_campaign(engine, world):
    for i in range(4):   # the same user, four messages
        _watch(engine, "u_phone0", i, [{"kind": "upi", "value": CAMPAIGN_UPI}], minutes=i)
    r = engine.post("/v1/decide", json=req(user=users_in(world)[3], payee=CAMPAIGN_UPI, amount=4_000,
                                           context={"lures": LURE}, rid="c_2",
                                           ts=SIM_NOW + timedelta(minutes=10))).json()
    assert "R13_scam_campaign" not in r["reasons"]


def test_campaign_evidence_alone_never_interrupts(engine, world):
    """Rule 5: a spreading payee is one family. With nothing else seen on this phone, no interruption."""
    _spread(engine)
    r = engine.post("/v1/decide", json=req(user=users_in(world)[4], payee=CAMPAIGN_UPI, amount=900,
                                           entry="qr", rid="c_3", ts=SIM_NOW + timedelta(minutes=10))).json()
    assert r["tier"] in ("T0", "T1")


def test_a_callers_number_in_the_campaign_is_call_evidence(engine, world):
    _spread(engine, phone=CALLBACK)
    call = {"call": {"active": True, "kind": "sim", "caller_number": "9812345670",
                     "caller_in_contacts": False, "started_min_ago": 4}, "lures": []}
    r = engine.post("/v1/decide", json=req(user=users_in(world)[5], payee="someone.else@oksbi", amount=2_500,
                                           context=call, rid="c_4", ts=SIM_NOW + timedelta(minutes=10))).json()
    feats = _features(engine, "c_4")
    assert feats["caller_in_campaign"] is True and feats["payee_in_campaign"] is False
    # The rules scorer recorded R13 as call-family evidence (not payee: the payee is someone else).
    from api.rule_scorer import signals
    sig = signals(feats)
    assert any(x["reason"] == "R13_scam_campaign" and x["family"] == "C" for x in sig), sig
    # No call number at all: unknown, never False (rule 1).
    engine.post("/v1/decide", json=req(user=users_in(world)[6], payee=CAMPAIGN_UPI, amount=2_500,
                                       context={"lures": LURE}, rid="c_5", ts=SIM_NOW + timedelta(minutes=10)))
    assert _features(engine, "c_5")["caller_in_campaign"] is None


def _details(engine, rid):
    return engine.get(f"/v1/transactions/{rid}").json()["details"]


def _features(engine, rid):
    """Every recorded payment's features (the transaction database keeps them, whatever the tier)."""
    return _details(engine, rid)["features"]


def test_one_campaign_lights_one_family_only():
    """Payee and caller both in the same campaign: one source, so it lights the payee family only."""
    pol = Policy()
    f = {"amount_inr": 5_000, "trusted_payee": False, "payee_registry_listed": False,
         "caller_registry_listed": False, "payee_fri_level": None, "caller_fri_level": None,
         "payee_approved_suspect": False, "payee_micro_anchor": False,
         "payee_in_campaign": True, "caller_in_campaign": True}
    s = overlay.apply({"p_scam": 0.2, "family_scores": {"C": 0.1, "L": 0.0, "P": 0.1, "B": 0.0},
                       "reasons": [], "playbook": None}, f, pol.cfg)
    assert s["family_scores"]["P"] >= 0.6 and s["family_scores"]["C"] == 0.1
    assert pol.decide(s, f, "S1", False, "u", SIM_NOW).tier == "T0"


def test_spreading_now_endpoint_shows_upi_and_hides_numbers(engine):
    _spread(engine, phone=CALLBACK)
    body = engine.get("/v1/campaigns/spreading").json()
    by_kind = {h["kind"]: h for h in body["handles"]}
    assert by_kind["upi"]["value"] == CAMPAIGN_UPI and by_kind["upi"]["users"] == 3 and by_kind["upi"]["spreading"]
    assert by_kind["phone"]["value"] is None
    engine.post("/sim/reset")
    assert engine.get("/v1/campaigns/spreading").json()["handles"] == []
