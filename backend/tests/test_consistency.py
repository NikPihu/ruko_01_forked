"""The same payment gets the same tier: a slow intel source is not a coin toss, and the alert
budget never silences a payment to a risky payee."""
import asyncio
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from api.intel import IntelAdapter
from api.main import create_app as create_engine
from intel_mock.app import create_app as create_mock
from sim.accounts import DEMO_MULE_UPI
from tests.test_decide import CFG, NOW, pump, req, users_in, world  # noqa: F401  (module fixture)

PAYEE = "ravi.kumar@oksbi"


class FakeIntel:
    """NPCI resolve -> bank payee-risk, and the registry, with a delay we control and a call count."""

    def __init__(self, delay_s: float = 0.0):
        self.delay_s = delay_s
        self.calls: dict[str, int] = {}

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls[path] = self.calls.get(path, 0) + 1
        await asyncio.sleep(self.delay_s)
        if path.startswith("/npci/resolve/"):
            return httpx.Response(200, json={"upi_id": PAYEE, "bank_code": "sbi"})
        if path.startswith("/banks/"):
            return httpx.Response(200, json={"features": {"uniq_payers_6h": 40}, "mulehunter": {"score": 0.9}})
        return httpx.Response(200, json={"listed": False})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self), base_url="http://intel")


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_a_late_answer_is_kept_for_the_next_payment():
    fake = FakeIntel(delay_s=0.2)
    intel = IntelAdapter(fake.client(), budget_s=0.15)

    async def go():
        first = await intel.lookup(PAYEE)          # resolve (0.2 s) alone is over the 0.15 s budget
        fake.delay_s = 0.5                         # and the next lookup would be too slow as well
        await asyncio.sleep(0.8)                   # the first answers arrive in the background
        second = await intel.lookup(PAYEE)
        return first, second

    first, second = run(go())
    assert first.status["npci"] == "timeout" and first.bank is None
    assert second.status["bank"] in ("ok", "cached:ok") and second.bank["mulehunter"]["score"] == 0.9


def test_a_recent_answer_stands_in_when_a_source_is_slow():
    fake = FakeIntel()
    intel = IntelAdapter(fake.client(), budget_s=0.15, cache_ttl_s=0.0)

    async def go():
        fresh = await intel.lookup(PAYEE)
        fake.delay_s = 0.5                         # the bank is slow now
        slow = await intel.lookup(PAYEE)
        return fresh, slow

    fresh, slow = run(go())
    assert fresh.status["bank"] == "ok"
    assert slow.status["bank"] == "cached:ok" and slow.bank == fresh.bank
    assert slow.status["npci"] == "cached:ok"


def test_an_old_answer_is_not_used():
    fake = FakeIntel()
    intel = IntelAdapter(fake.client(), budget_s=0.1, cache_ttl_s=0.0, stale_s=0.0)

    async def go():
        await intel.lookup(PAYEE)
        fake.delay_s = 0.5
        return await intel.lookup(PAYEE)

    r = run(go())
    assert r.status["bank"] == "timeout" and r.bank is None   # unknown, never safe


def test_two_payments_asking_at_once_share_one_request():
    fake = FakeIntel(delay_s=0.05)
    intel = IntelAdapter(fake.client(), budget_s=0.5)

    async def go():
        return await asyncio.gather(intel.lookup(PAYEE), intel.lookup(PAYEE))

    a, b = run(go())
    assert a.status == b.status and a.bank == b.bank
    assert fake.calls[f"/npci/resolve/{PAYEE}"] == 1


# ---------- through the engine ----------

@pytest.fixture()
def stack(world):  # noqa: F811
    mock = create_mock(world[0])
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock), base_url="http://mock")
    return TestClient(create_engine(world[0], intel_client=client, intel_cache_ttl_s=0, log_path=None,
                                    evidence_async=False)), TestClient(mock)


def test_repeated_payment_to_a_mule_is_never_silenced(stack, world):  # noqa: F811
    """Same user, same payment to the demo mule, again and again: once it is interrupted, the alert
    budget never drops it back to a tip (it used to go T2, T2, then T1 for good)."""
    engine, mock = stack
    pump(mock, world)
    user = users_in(world)[20]
    tiers = []
    for i in range(8):
        r = engine.post("/v1/decide", json=req(user=user, amount=5_000, entry="typed", rid=f"m{i}",
                                               ts=NOW + __import__("datetime").timedelta(minutes=5 * i))).json()
        tiers.append(r["tier"])
    first_interrupt = next((i for i, t in enumerate(tiers) if t >= "T2"), None)
    assert first_interrupt is not None, tiers
    assert all(t >= "T2" for t in tiers[first_interrupt:]), tiers


def test_same_payment_same_answer_in_fresh_engines(world):  # noqa: F811
    """Two engines, same world, same request: the same tier and reasons (no randomness in the path)."""
    out = []
    for _ in range(2):
        mock = create_mock(world[0])
        mc = TestClient(mock)
        pump(mc, world)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock), base_url="http://mock")
        engine = TestClient(create_engine(world[0], intel_client=client, log_path=None, evidence_async=False))
        r = engine.post("/v1/decide", json=req(user=users_in(world)[21], amount=5_000, entry="typed")).json()
        out.append((r["tier"], r["reasons"]))
    assert out[0] == out[1]
