"""c2-0.11: money a user received, read from a bank SMS on the phone, stored for the console."""
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import api.main
from api.main import create_app as create_engine
from evidence.store import pseudonym
from schema.events import CONTRACT_VERSION, MoneyReceived
from store.db import TxnStore
from test_decide import NOW, mock, users_in, world  # noqa: F401


@pytest.fixture()
def engine(world, mock, monkeypatch):
    monkeypatch.setattr(api.main, "DEADLINE_S", 10.0)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock[0]), base_url="http://mock")
    return TestClient(create_engine(world[0], intel_client=client, intel_cache_ttl_s=0, log_path=None,
                                    evidence_async=False, intel_budget_s=5.0))


def credit(user, eid="r_1", sender="arjun.pandey@okicici", inr=500.0, minutes=0):
    return {"event_id": eid, "user_id": user, "sender_upi_id": sender, "amount_inr": inr,
            "ts": (NOW + timedelta(minutes=minutes)).isoformat(), "source": "bank_sms"}


# ---------- unit: the store on its own ----------

def test_store_keeps_each_credit_once_and_pseudonymises_the_receiver():
    s = TxnStore()
    assert s.record_received("r_1", "u_a", "Arjun.Pandey@okicici ", 500.0, NOW, "bank_sms") is True
    assert s.record_received("r_1", "u_a", "arjun.pandey@okicici", 500.0, NOW, "bank_sms") is False
    [row] = s.received()
    assert row["user_hash"] == pseudonym("u_a") and row["sender_upi"] == "arjun.pandey@okicici"
    assert s.counts()["received"] == 1
    s.reset()
    assert s.received() == []


def test_a_credit_with_no_named_sender_stays_unknown():
    s = TxnStore()
    s.record_received("r_1", "u_a", None, 250.0, NOW, "bank_sms")
    assert s.received()[0]["sender_upi"] is None   # rule 1: unknown, never a made-up sender


# ---------- the endpoint ----------

def test_received_money_is_listed_newest_first_and_on_the_users_timeline(engine, world):
    user = users_in(world)[0]
    r = engine.post("/v1/payment/received", json=credit(user)).json()
    assert r == {"event_id": "r_1", "recorded": True, "contract_version": CONTRACT_VERSION}
    engine.post("/v1/payment/received", json=credit(user, "r_2", "priya.nair22@ybl", 1200.0, minutes=5))
    listed = engine.get("/v1/received").json()
    assert listed["count"] == 2
    assert [x["sender_upi"] for x in listed["received"]] == ["priya.nair22@ybl", "arjun.pandey@okicici"]
    assert engine.get("/v1/received", params={"sender": "priya.nair22@ybl"}).json()["count"] == 1
    timeline = engine.get(f"/v1/users/{pseudonym(user)}/timeline").json()
    rows = timeline if isinstance(timeline, list) else timeline.get("timeline", timeline.get("events", []))
    assert sum(1 for t in rows if t["kind"] == "received") == 2


def test_a_retried_credit_is_recorded_once(engine, world):
    user = users_in(world)[0]
    assert engine.post("/v1/payment/received", json=credit(user)).json()["recorded"] is True
    assert engine.post("/v1/payment/received", json=credit(user)).json()["recorded"] is False
    assert engine.get("/v1/received").json()["count"] == 1


def test_received_money_is_not_a_payment_check(engine, world):
    user = users_in(world)[0]
    engine.post("/v1/payment/received", json=credit(user))
    assert engine.get("/v1/transactions").json()["count"] == 0


def test_a_credit_never_carries_the_sms_text():
    with pytest.raises(ValidationError):   # rule 2; extra="forbid"
        MoneyReceived.model_validate({**credit("u_a"), "text": "Rs.500.00 credited to A/c XX4821"})
    with pytest.raises(ValidationError):
        MoneyReceived.model_validate(credit("u_a", inr=0))


# ---------- c2-0.12: the sender's name, and credits in the payment graph ----------

PNB = {"sender_upi_id": "rahul@upi", "sender_name": "RAHUL  SHARMA", "amount_inr": 30.0}


def test_the_senders_name_is_stored_plain_and_the_receiver_stays_a_pseudonym(engine, world):
    user = users_in(world)[0]
    engine.post("/v1/payment/received", json={**credit(user), **PNB})
    [row] = engine.get("/v1/received").json()["received"]
    assert row["sender_name"] == "RAHUL SHARMA" and row["sender_upi"] == "rahul@upi"
    assert row["user_hash"] == pseudonym(user) and user not in str(row)   # rule 7


def test_a_credit_is_a_sender_to_user_edge_with_the_senders_name(engine, world):
    from graph.store import user_node
    user = users_in(world)[0]
    engine.post("/v1/payment/received", json={**credit(user), **PNB})
    graph = engine.app.state.graph
    edge = graph.edges[("rahul@upi", user_node(user))]
    assert edge.n == 1 and edge.inr == 30.0 and edge.sources == {"received"}
    assert graph.marks["rahul@upi"]["name"] == "RAHUL SHARMA"
    hood = engine.get("/v1/graph/account/rahul@upi").json()
    assert any(n["marks"].get("name") == "RAHUL SHARMA" for n in hood["nodes"])


def test_small_credits_from_one_sender_to_many_users_become_crowd_evidence(engine, world):
    users = users_in(world)[:10]   # new users count half (anti-sybil): 10 x 0.5 = 5 votes
    for i, u in enumerate(users):
        engine.post("/v1/payment/received", json=credit(u, f"r_{i}", "rewards.desk@ybl", 150.0, minutes=i))
    engine.post("/v1/payment/received", json=credit(users[0], "r_big", "salary.co@hdfc", 25_000.0))
    graph = engine.app.state.graph
    now = NOW + timedelta(minutes=15)
    assert graph.account_signals("rewards.desk@ybl", now)["crowd"] is True
    assert "salary.co@hdfc" not in graph.bait   # above bait_max_inr: an edge, not a bait vote


def test_a_credit_with_no_sender_or_a_retry_adds_nothing_to_the_graph(engine, world):
    user = users_in(world)[0]
    engine.post("/v1/payment/received", json=credit(user, "r_1", None, 400.0))
    engine.post("/v1/payment/received", json={**credit(user, "r_2"), **PNB})
    engine.post("/v1/payment/received", json={**credit(user, "r_2"), **PNB})   # retried
    graph = engine.app.state.graph
    assert sum(1 for (a, b) in graph.edges if b.startswith("u:")) == 1
    assert graph.edges[("rahul@upi", next(b for (a, b) in graph.edges if a == "rahul@upi"))].n == 1


def test_a_database_file_from_c2_0_11_gets_the_name_column(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE received (event_id TEXT PRIMARY KEY, user_hash TEXT NOT NULL, sender_upi TEXT, "
                "amount_inr REAL NOT NULL, ts TEXT NOT NULL, source TEXT NOT NULL)")
    con.commit(), con.close()
    s = TxnStore(path)
    assert s.record_received("r_1", "u_a", "rahul@upi", 30.0, NOW, "bank_sms", "RAHUL SHARMA")
    assert s.received()[0]["sender_name"] == "RAHUL SHARMA"


def test_an_episode_report_and_the_credit_itself_count_the_money_once():
    from types import SimpleNamespace
    from graph.store import GraphStore, user_node
    acc = SimpleNamespace(upi_id="rahul@upi", role="bait_sender", inr=30.0, first_seen_min_ago=1.0)
    ep = SimpleNamespace(user_id="u_a", accounts=[acc])
    for order in ("credit_first", "episode_first"):
        g = GraphStore()
        steps = [lambda: g.add_credit("rahul@upi", "u_a", 30.0, NOW, "RAHUL SHARMA"), lambda: g.add_episode(ep, NOW)]
        for step in (steps if order == "credit_first" else steps[::-1]):
            step()
        g.add_episode(ep, NOW + timedelta(minutes=5))   # the same episode re-sent on its next state change
        e = g.edges[("rahul@upi", user_node("u_a"))]
        assert (e.n, e.inr) == (1, 30.0), order
        assert e.sources == {"episode", "received"} and user_node("u_a") in g.bait["rahul@upi"]
