"""The transaction database (store/db.py): every check, its full decision and its outcome."""
import json
import time
from datetime import timedelta

import pytest

import api.main
from api.main import create_app as create_engine, load_scorer
from evidence.store import pseudonym
from store.db import TxnStore
from test_decide import (DEMO_KIRANA_UPI, DEMO_MEENA, MEENA_CONTEXT, NOW, mock, pump, req, users_in,  # noqa: F401
                         world)

import httpx
from fastapi.testclient import TestClient


@pytest.fixture()
def engine(world, mock, monkeypatch):
    """Functional checks with generous time limits (see test_session.py)."""
    monkeypatch.setattr(api.main, "DEADLINE_S", 10.0)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock[0]), base_url="http://mock")
    return TestClient(create_engine(world[0], intel_client=client, intel_cache_ttl_s=0, log_path=None,
                                    evidence_async=False, intel_budget_s=5.0))


def outcome(rid, user, payee, amount, status="completed", ts=NOW):
    return {"request_id": rid, "user_id": user, "payee_upi_id": payee, "amount_inr": amount, "status": status,
            "ts": (ts + timedelta(minutes=1)).isoformat()}


def test_every_check_is_recorded_with_its_decision(engine, mock, world):
    pump(mock[1], world)
    r = engine.post("/v1/decide", json=req(context=MEENA_CONTEXT, says="government", rid="p_meena")).json()
    user = users_in(world)[0]
    engine.post("/v1/decide", json=req(user=user, payee=DEMO_KIRANA_UPI, amount=180, entry="qr", rid="p_kirana"))

    rows = engine.get("/v1/transactions").json()
    assert rows["count"] == 2
    meena = engine.get("/v1/transactions/p_meena").json()
    assert meena["payment"]["tier"] == r["tier"] and meena["payment"]["reasons"] == r["reasons"]
    assert meena["payment"]["user_hash"] == pseudonym(DEMO_MEENA)        # rule 7: never the plain user id
    assert DEMO_MEENA not in json.dumps(meena)
    d = meena["details"]
    assert d["p_scam"] is not None and set(d["family_scores"]) == {"C", "L", "P", "B"}
    assert d["features"]["remote_control"] is True and d["lit_families"]
    assert engine.get("/v1/transactions", params={"min_tier": "T3"}).json()["count"] == 1


def test_decision_records_the_steps_and_the_playbook_search(engine, mock, world):
    pump(mock[1], world)
    engine.post("/v1/decide", json=req(context=MEENA_CONTEXT, says="government", rid="p_steps"))
    d = engine.get("/v1/transactions/p_steps").json()["details"]
    assert {"unknown_call", "remote_control", "new_payee"} <= set(d["steps"]["seen"])
    assert "lure:kyc" not in d["steps"]["unmeasured"]                     # lures: [] was sent, so measured
    top = d["playbook_search"][0]
    assert top["name"] == "digital_arrest" and top["similarity"] > 0.5 and "remote_control" in str(top["matched"])


def test_outcome_updates_the_payment(engine, world):
    user = users_in(world)[0]
    engine.post("/v1/decide", json=req(user=user, payee=DEMO_KIRANA_UPI, amount=180, entry="qr", rid="p_1"))
    engine.post("/v1/payment/outcome", json=outcome("p_1", user, DEMO_KIRANA_UPI, 180))
    p = engine.get("/v1/transactions/p_1").json()["payment"]
    assert p["status"] == "completed" and p["outcome_ts"]
    assert engine.get("/v1/transactions", params={"status": "completed"}).json()["count"] == 1


def test_app_response_never_carries_scores(engine, mock, world):
    pump(mock[1], world)
    r = engine.post("/v1/decide", json=req(context=MEENA_CONTEXT, says="government")).json()
    assert not {"p_scam", "family_scores", "features"} & set(r)


def test_timeline_and_reset(engine, world):
    user = users_in(world)[0]
    engine.post("/v1/decide", json=req(user=user, payee=DEMO_KIRANA_UPI, amount=180, entry="qr", rid="p_t"))
    engine.post("/v1/payment/outcome", json=outcome("p_t", user, DEMO_KIRANA_UPI, 180, status="cancelled"))
    events = engine.get(f"/v1/users/{pseudonym(user)}/timeline").json()["events"]
    assert [e["kind"] for e in events] == ["payment", "outcome"]
    assert engine.get("/v1/store/stats").json()["rows"]["payments"] == 1
    engine.post("/sim/reset")
    assert engine.get("/v1/store/stats").json()["rows"]["payments"] == 0


def test_each_test_starts_empty(engine):
    assert engine.get("/v1/transactions").json()["count"] == 0


def test_a_retried_request_keeps_one_row(engine, world):
    user = users_in(world)[0]
    for _ in range(2):
        engine.post("/v1/decide", json=req(user=user, payee=DEMO_KIRANA_UPI, amount=180, entry="qr", rid="p_r"))
    assert engine.get("/v1/transactions").json()["count"] == 1


def test_fail_open_answers_are_recorded(engine, world):
    def boom(_):
        raise RuntimeError("scorer down")
    engine.app.state.score = boom
    r = engine.post("/v1/decide", json=req(rid="p_f")).json()
    assert r["fail_open"] is True
    p = engine.get("/v1/transactions/p_f").json()["payment"]
    assert p["fail_open"] is True and p["tier"] == "T0"


def test_file_database_keeps_a_run_and_exports(tmp_path):
    from store.export import export
    db = tmp_path / "ruko.db"
    s = TxnStore(db)
    s.record_decision({"payment_id": "p", "user_id": "u", "payee_upi": "x@ybl", "amount_inr": 10.0,
                       "entry_method": "typed", "ts": NOW, "tier": "T0", "reasons": [], "fail_open": False},
                      {"features": {"amount_inr": 10.0}, "p_scam": 0.01, "family_scores": {"C": 0, "L": 0, "P": 0, "B": 0}})
    assert TxnStore(db).payment("p")["amount_inr"] == 10.0
    assert export(db, tmp_path / "out.csv") == 1


def test_scorer_switch_falls_back_to_rules(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def no_model(name, *a, **k):
        if name == "model":
            raise ImportError("no ml on this machine")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_model)
    _, version = load_scorer("ml")
    assert version.startswith("rules")


def test_recording_keeps_decide_fast(world, mock):
    """With the real limits and async writes, recording adds nothing noticeable to /v1/decide."""
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock[0]), base_url="http://mock")
    eng = TestClient(create_engine(world[0], intel_client=client, log_path=None, evidence_async=True))
    user = users_in(world)[0]
    took = []
    for i in range(30):
        t = time.perf_counter()
        eng.post("/v1/decide", json=req(user=user, payee=DEMO_KIRANA_UPI, amount=180, entry="qr", rid=f"p_{i}",
                                        ts=NOW + timedelta(minutes=i)))
        took.append((time.perf_counter() - t) * 1000)
    assert sorted(took)[int(0.95 * len(took)) - 1] < 150
