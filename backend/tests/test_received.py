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
