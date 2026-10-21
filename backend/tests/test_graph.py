"""Payment graph (task-scam-watcher.md §9): crowd signal, money loop, and the guard rails."""
import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from api.main import create_app as create_engine
from graph.store import GraphStore
from intel_mock.app import create_app as create_mock
from schema.events import EpisodeEvent
from sim.config import SimConfig
from sim.generate import build_world, write_world

CFG = SimConfig(seed=3, n_users=400, n_days=20, scam_rate=0.05)
NOW = CFG.end - timedelta(hours=2)
EXAMPLE = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "examples" / "episode_event_active.json")
                     .read_text(encoding="utf-8"))


def event(user, accounts, eid, state="active", trigger="active"):
    body = {**EXAMPLE, "event_id": eid, "user_id": user, "ts": NOW.isoformat(), "trigger": trigger,
            "summary": {**EXAMPLE["summary"], "state": state}, "accounts": accounts}
    return body


def bait(upi, inr=150):
    return {"upi_id": upi, "role": "bait_sender", "n": 1, "inr": inr, "first_seen_min_ago": 60}


def payee(upi, inr=2_000, step=1):
    return {"upi_id": upi, "role": "payee", "n": 1, "inr": inr, "first_seen_min_ago": 30, "via": "this_app", "step": step}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    out = tmp_path_factory.mktemp("data")
    tables = build_world(CFG)
    write_world(tables, CFG, out)
    return out, tables


@pytest.fixture()
def stack(world):
    mock = create_mock(world[0])
    mock_client = TestClient(mock)
    mock_client.post("/sim/clock", json={"set": NOW.isoformat()})
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock), base_url="http://mock")
    engine = TestClient(create_engine(world[0], intel_client=client, intel_cache_ttl_s=0, log_path=None,
                                      evidence_async=False))
    return engine, mock_client


# ---------- unit: the store on its own ----------

def test_forty_bait_events_from_one_sender_light_the_fanout():
    g = GraphStore()
    for i in range(40):
        g.add_episode(EpisodeEvent.model_validate(event(f"u_{i}", [bait("task.reward@ybl")], f"e{i}", "watching", "watching")),
                      NOW - timedelta(days=3))
    s = g.account_signals("task.reward@ybl", NOW)
    assert s["bait_sender_fanout_7d"] >= 20 and s["crowd"]  # new users count half


def test_crowd_votes_from_brand_new_users_count_for_less():
    g = GraphStore()
    for i in range(4):
        g.add_episode(EpisodeEvent.model_validate(event(f"u_{i}", [bait("x@ybl")], f"e{i}", "watching", "watching")), NOW)
    assert g.account_signals("x@ybl", NOW)["bait_sender_fanout_7d"] == 2.0


def test_events_per_device_are_capped():
    g = GraphStore()
    results = [g.add_episode(EpisodeEvent.model_validate(event("u_spam", [bait(f"s{i}@ybl")], f"e{i}")), NOW)
               for i in range(30)]
    assert results.count(False) == 10


def test_loop_is_unknown_without_bank_flows():
    g = GraphStore()
    g.add_episode(EpisodeEvent.model_validate(event("u_1", [bait("b@ybl"), payee("p@ybl")], "e1")), NOW)
    assert g.account_signals("p@ybl", NOW)["money_loop"] is None
    g.add_bank_flows("p@ybl", None)
    assert g.account_signals("p@ybl", NOW)["money_loop"] is None


def test_loop_found_through_a_shared_cash_out():
    g = GraphStore()
    g.add_episode(EpisodeEvent.model_validate(event("u_1", [bait("b@ybl"), payee("p@ybl")], "e1")), NOW)
    g.add_bank_flows("p@ybl", {"as_of": NOW.isoformat(), "outbound": [{"upi_id": "hub@ybl", "n": 3, "inr": 9000}]})
    g.add_bank_flows("b@ybl", {"as_of": NOW.isoformat(), "outbound": [{"upi_id": "hub@ybl", "n": 1, "inr": 500}]})
    s = g.account_signals("p@ybl", NOW)
    assert s["money_loop"] is True and "hub@ybl" in s["loop_path"]


def test_no_loop_when_flows_were_visible_and_unlinked():
    g = GraphStore()
    g.add_episode(EpisodeEvent.model_validate(event("u_1", [bait("b@ybl"), payee("p@ybl")], "e1")), NOW)
    g.add_bank_flows("p@ybl", {"as_of": NOW.isoformat(), "outbound": [{"upi_id": "rent@ybl", "n": 1, "inr": 9000}]})
    assert g.account_signals("p@ybl", NOW)["money_loop"] is False


def test_old_edges_expire_unless_they_are_evidence():
    g = GraphStore()
    g.add_payment("u_1", "old@ybl", 100, NOW - timedelta(days=40))
    g.add_payment("u_2", "kept@ybl", 100, NOW - timedelta(days=40))
    g.protect(["kept@ybl", next(a for a, b in g.edges if b == "kept@ybl")])
    g.expire(NOW)
    assert not any(b == "old@ybl" for _, b in g.edges) and any(b == "kept@ybl" for _, b in g.edges)


# ---------- integration: mock bank flows and the engine ----------

def mule_and_cash_out(world, partner=None):
    """A mule that forwarded money to a cash-out account in the last 7 days of the world."""
    led, acc = world[1]["ledger"], world[1]["accounts"].set_index("upi_id")
    fwd = led[(led.flow == "mule_forward") & (led.ts >= NOW - timedelta(days=7)) & (led.ts <= NOW)]
    for r in fwd.itertuples():
        if acc.loc[r.to_upi].mule_kind == "cash_out" and (partner is None or bool(acc.loc[r.from_upi].partner_bank) == partner):
            return r.from_upi, r.to_upi
    pytest.skip("no forwarding mule in this world")


@pytest.mark.parametrize("visibility", ["partner", "dpip"])
def test_loop_found_when_the_bank_shares(stack, world, visibility):
    engine, mock = stack
    mock.post("/sim/settings", json={"visibility": visibility})
    mule, cash_out = mule_and_cash_out(world, partner=True if visibility == "partner" else None)
    # The "rewards" came from the same cash-out account the payee forwards to.
    r = engine.post("/v1/episode", json=event("u_000001", [bait(cash_out), payee(mule)], f"loop_{visibility}")).json()
    assert "R11_ring_link" in r["reasons"]
    sig = engine.app.state.graph.account_signals(mule, NOW)
    assert sig["money_loop"] is True and cash_out in sig["loop_path"]


def test_loop_is_unknown_when_no_bank_shares(stack, world):
    engine, mock = stack
    mock.post("/sim/settings", json={"visibility": "none"})
    mule, cash_out = mule_and_cash_out(world)
    engine.post("/v1/episode", json=event("u_000001", [bait(cash_out), payee(mule)], "loop_none"))
    assert engine.app.state.graph.account_signals(mule, NOW)["money_loop"] is None


def test_crowd_evidence_alone_never_reaches_t2(stack, world):
    engine, _ = stack
    users = world[1]["users"]
    honest = users.upi_id.iloc[-1]  # an ordinary person's account, framed by fake episodes
    for i in range(8):
        engine.post("/v1/episode", json=event(users.user_id.iloc[i], [bait("frame.bait@ybl"), payee(honest)], f"crowd_{i}"))
    assert engine.app.state.graph.account_signals(honest, NOW)["crowd"]
    r = engine.post("/v1/decide", json={"request_id": "r_c", "user_id": users.user_id.iloc[20], "payee_upi_id": honest,
                                        "amount_inr": 2_000, "entry_method": "typed", "ts": NOW.isoformat(),
                                        "context": None}).json()
    assert r["tier"] in ("T0", "T1")


# ---------- discovery and review (§9.5, §9.7) ----------

def test_discovery_finds_an_unlisted_account_next_to_a_listed_mule():
    from graph import discover as d
    g = GraphStore()
    # Two victims each paid a listed mule and an account nobody has listed yet.
    for i in range(2):
        g.add_episode(EpisodeEvent.model_validate(event(f"u_v{i}", [bait("b@ybl"), payee("listed.mule@ybl"),
                                                                    payee("fresh.mule@ybl", step=2)], f"d{i}")), NOW)
    g.add_bank_flows("fresh.mule@ybl", {"as_of": NOW.isoformat(), "outbound": [
        {"upi_id": "hub@ybl", "n": 4, "inr": 40_000, "median_hold_min": 12}]})
    g.mark("listed.mule@ybl", listed=True)
    g.mark("big.shop@ybl", verified_merchant=True)
    out = d.discover(g, {}, NOW)
    names = [s["upi_id"] for s in out]
    assert "fresh.mule@ybl" in names and "listed.mule@ybl" not in names  # seeds aren't suspects
    fresh = next(s for s in out if s["upi_id"] == "fresh.mule@ybl")
    assert fresh["ring_id"] and "paid" in fresh["why"] and not fresh["review"]["approved"]
    assert all(not s["upi_id"].startswith("u:") for s in out)  # victims are never suspects


def test_a_suspect_needs_two_different_analysts():
    from graph import discover as d
    reviews = {}
    d.review(reviews, "fresh.mule@ybl", "asha", "approve")
    d.review(reviews, "fresh.mule@ybl", "asha", "approve")
    assert not reviews["fresh.mule@ybl"].approved
    d.review(reviews, "fresh.mule@ybl", "ravi", "approve")
    assert reviews["fresh.mule@ybl"].approved
    d.review(reviews, "fresh.mule@ybl", "meera", "reject")
    assert not reviews["fresh.mule@ybl"].approved


def test_console_endpoints(stack, world):
    engine, _ = stack
    mule, cash_out = mule_and_cash_out(world)
    engine.post("/v1/episode", json=event("u_000002", [bait(cash_out), payee(mule)], "console_1"))
    g = engine.get(f"/v1/graph/account/{mule}?hops=2").json()
    assert g["center"] == mule and g["edges"] and "money_loop" in g["signals"]
    s = engine.get("/v1/graph/suspects").json()
    assert "suspects" in s and s["approvals_needed"] == 2 and s["last_run"]["error"] is None
    r = engine.post(f"/v1/graph/suspects/{mule}/review", json={"reviewer": "asha", "decision": "approve"}).json()
    assert r["approved"] is False
    assert engine.post(f"/v1/graph/suspects/{mule}/review", json={"reviewer": "x", "decision": "maybe"}).status_code == 422
    assert "cytoscape" in engine.get("/console/graph").text
