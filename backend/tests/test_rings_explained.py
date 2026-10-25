"""Rings start from payments RUKO stopped, and every ring explains itself in words."""
import httpx
import pytest
from fastapi.testclient import TestClient

import api.main
from api.main import create_app as create_engine
from graph import discover as d
from graph.store import GraphStore
from test_decide import MEENA_CONTEXT, NOW, mock, pump, req, world  # noqa: F401
from sim.accounts import DEMO_MULE_UPI


def test_a_stopped_payee_seeds_discovery():
    g = GraphStore()
    g.mark("mule@ybl", interrupted="T3")
    assert "stopped (T3)" in d.seeds(g, {})["mule@ybl"]


def test_ring_explanation_says_how_each_account_is_tied_in():
    g = GraphStore()
    g.mark("mule@ybl", interrupted="T3")
    g.add_bank_flows("mule@ybl", {"as_of": NOW.isoformat(), "outbound": [
        {"upi_id": "cash.a@ybl", "n": 3, "inr": 60_000, "median_hold_min": 9},
        {"upi_id": "cash.b@ybl", "n": 2, "inr": 30_000, "median_hold_min": 40}]})
    rings = d.ring_view(g, {}, NOW)
    assert len(rings) == 1
    ex = rings[0]["explanation"]
    assert ex["started_from"] == [{"upi_id": "mule@ybl", "why": d.seeds(g, {})["mule@ybl"]}]
    assert "received ₹60,000 from mule@ybl, passed on within 9 min" in ex["linked_by"]["cash.a@ybl"]
    assert "passed on" not in ex["linked_by"]["cash.b@ybl"]           # 40 min is not fast
    assert ex["steps"][0].startswith("Started from mule@ybl")
    assert "two different analysts" in ex["steps"][-1]
    accs = {a["upi_id"]: a for a in rings[0]["accounts"]}
    assert accs["mule@ybl"]["linked_by"] is None and accs["cash.a@ybl"]["linked_by"]


@pytest.fixture()
def engine(world, mock, monkeypatch):
    monkeypatch.setattr(api.main, "DEADLINE_S", 10.0)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock[0]), base_url="http://mock")
    # A persistent client: the bank lookup runs as a background task on the server's event loop.
    with TestClient(create_engine(world[0], intel_client=client, intel_cache_ttl_s=0, log_path=None,
                                  evidence_async=False, intel_budget_s=5.0)) as tc:
        yield tc


def test_stopping_a_mule_payment_produces_an_explained_ring(engine, mock, world):
    pump(mock[1], world)
    assert engine.get("/v1/graph/rings").json()["rings"] == []
    r = engine.post("/v1/decide", json=req(context=MEENA_CONTEXT, says="government")).json()
    assert r["tier"] in ("T2", "T3", "T4")
    import time
    for _ in range(50):   # the bank's flows arrive in the background, off the payment path
        rings = engine.get("/v1/graph/rings").json()["rings"]
        if rings:
            break
        time.sleep(0.1)
    assert rings and rings[0]["explanation"]["started_from"][0]["upi_id"] == DEMO_MULE_UPI
    assert any("joined because" in s for s in rings[0]["explanation"]["steps"])


def test_a_quiet_payment_seeds_nothing(engine, mock, world):
    r = engine.post("/v1/decide", json=req(payee="shreeganesh.kirana@okaxis", amount=150, entry="qr")).json()
    assert r["tier"] in ("T0", "T1")
    assert engine.get("/v1/graph/rings").json()["rings"] == []
