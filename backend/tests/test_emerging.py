"""A4: emerging patterns. A scam workflow with no known playbook surfaces for analysts."""
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

import api.main
from api.main import create_app as create_engine
from test_decide import (DEMO_KIRANA_UPI, DEMO_MULE_UPI, MEENA_CONTEXT, NOW, mock, pump, req,  # noqa: F401
                         users_in, world)

# The hidden 7th type: "your son is in hospital" -- an unknown phone call, the UPI ID pasted from a
# message right after switching apps, no screen control, no scam-script message the phone knows.
RELATIVE_EMERGENCY = {
    "call": {"active": True, "kind": "sim", "caller_number": "+919800011122", "caller_in_contacts": False,
             "started_min_ago": 6},
    "lures": [],
    "session": {"amount_digits": 5, "amount_gap_vs_usual": 1.1, "payee_pasted": True,
                "pasted_within_s_of_return": 5.0, "app_switches": 1},
}


@pytest.fixture()
def engine(world, mock, monkeypatch):
    monkeypatch.setattr(api.main, "DEADLINE_S", 10.0)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock[0]), base_url="http://mock")
    return TestClient(create_engine(world[0], intel_client=client, intel_cache_ttl_s=0, log_path=None,
                                    evidence_async=False, intel_budget_s=5.0))


def run_hidden_type(engine, world, n=6):
    tiers = []
    for i, user in enumerate(users_in(world)[:n]):
        r = engine.post("/v1/decide", json=req(user=user, payee=DEMO_MULE_UPI, amount=25_000, context=RELATIVE_EMERGENCY,
                                               rid=f"re_{i}", ts=NOW + timedelta(minutes=30 * i))).json()
        tiers.append(r)
    return tiers


def test_hidden_scam_type_shows_up_as_an_emerging_pattern(engine, mock, world):
    pump(mock[1], world)
    answers = run_hidden_type(engine, world)
    assert all(a["playbook"] is None for a in answers)          # no known playbook names it
    pats = engine.get("/v1/patterns/emerging").json()["patterns"]
    assert len(pats) == 1
    p = pats[0]
    assert p["people"] == 6 and p["payments"] == 6
    assert "unknown caller" in p["description"] and "pasted" in p["description"]
    assert "Matches no known scam type" in p["summary"]


def test_known_scam_types_are_not_listed(engine, mock, world):
    pump(mock[1], world)
    for i, user in enumerate(users_in(world)[:6]):
        engine.post("/v1/decide", json=req(user=user, context=MEENA_CONTEXT, says="government", rid=f"da_{i}",
                                           ts=NOW + timedelta(minutes=30 * i)))
    assert engine.get("/v1/patterns/emerging").json()["patterns"] == []


def test_one_person_repeating_is_not_a_pattern(engine, mock, world):
    pump(mock[1], world)
    user = users_in(world)[0]
    for i in range(6):
        engine.post("/v1/decide", json=req(user=user, payee=DEMO_MULE_UPI, amount=25_000, context=RELATIVE_EMERGENCY,
                                           rid=f"one_{i}", ts=NOW + timedelta(minutes=30 * i)))
    assert engine.get("/v1/patterns/emerging").json()["patterns"] == []


def test_calm_payments_are_not_patterns(engine, world):
    for i, user in enumerate(users_in(world)[:6]):
        engine.post("/v1/decide", json=req(user=user, payee=DEMO_KIRANA_UPI, amount=180, entry="qr", rid=f"k_{i}"))
    assert engine.get("/v1/patterns/emerging").json()["patterns"] == []


def test_naming_drafts_a_playbook_and_dismissing_hides_it(engine, mock, world):
    pump(mock[1], world)
    run_hidden_type(engine, world)
    pid = engine.get("/v1/patterns/emerging").json()["patterns"][0]["pattern_id"]
    named = engine.post(f"/v1/patterns/{pid}/review", json={"analyst": "asha", "action": "name",
                                                            "name": "Relative emergency"}).json()
    assert named["status"] == "named" and "name: relative_emergency" in named["draft_playbook"]
    still = engine.get("/v1/patterns/emerging").json()["patterns"][0]
    assert still["review"]["status"] == "named"
    engine.post(f"/v1/patterns/{pid}/review", json={"analyst": "ravi", "action": "dismiss"})
    assert engine.get("/v1/patterns/emerging").json()["patterns"] == []


def test_finding_patterns_never_changes_a_decision(engine, mock, world):
    pump(mock[1], world)
    before = run_hidden_type(engine, world, n=3)
    engine.get("/v1/patterns/emerging")
    again = engine.post("/v1/decide", json=req(user=users_in(world)[0], payee=DEMO_MULE_UPI, amount=25_000,
                                               context=RELATIVE_EMERGENCY, rid="re_again",
                                               ts=NOW + timedelta(minutes=1))).json()
    assert again["playbook"] is None and before[0]["playbook"] is None
