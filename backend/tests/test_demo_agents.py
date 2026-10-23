"""Step 9: the demo agents. Every scripted scenario ends the way it should."""
import httpx
import pytest
from fastapi.testclient import TestClient

import api.main
from api.main import create_app as create_engine
from demo import agents
from test_decide import NOW, mock, world  # noqa: F401


@pytest.fixture()
def engine(world, mock, monkeypatch):
    monkeypatch.setattr(api.main, "DEADLINE_S", 10.0)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock[0]), base_url="http://mock")
    return TestClient(create_engine(world[0], intel_client=client, intel_cache_ttl_s=0, log_path=None,
                                    evidence_async=False, intel_budget_s=5.0))


def test_every_scenario_ends_as_expected(engine, mock, world):
    w = agents.load_world(world[0])
    agents.pump_mule(mock[1], w)
    rows = agents.run(engine, w, NOW)
    bad = [r for r in rows if not r["ok"]]
    assert not bad, bad
    assert {r["scenario"] for r in rows} == {s.name for s in agents.SCENARIOS}


def test_hidden_scam_type_shows_up_for_analysts(engine, mock, world):
    w = agents.load_world(world[0])
    agents.pump_mule(mock[1], w)
    agents.run(engine, w, NOW, ["relative_emergency"])
    pats = engine.get("/v1/patterns/emerging").json()["patterns"]
    assert len(pats) == 1 and pats[0]["people"] >= 5
    auto = engine.get(f"/v1/graph/account/{w.fresh_mule}").json()["signals"]["automation"]
    assert auto["automated"] is True and auto["side"] == "receives"

