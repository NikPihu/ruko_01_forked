"""The replay must compute exactly the features the live engine computes for the same requests.

Both sides get the same world (ledger cut 3 days before the end) and the same request sequence
from after the cut. The live side is the real engine over HTTP against the real mock services,
with the mock clock set to each request's time; the replay side calls the same code directly.
"""
import math
from datetime import timedelta

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api.main
from api import rule_scorer
from dataset.phone_view import PhoneView, Traits, keyed_rng
from dataset.replay import EngineReplay, bank_baseline
from intel_mock.app import create_app as create_mock
from intel_mock.store import Store
from schema.events import DecideRequest
from sim.config import SimConfig
from sim.generate import build_world, write_world

CFG = SimConfig(seed=3, n_users=300, n_days=20, scam_rate=0.05)
CUT = CFG.end - timedelta(days=3)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    tables = build_world(CFG)
    led = tables["ledger"]
    truncated = {**tables, "ledger": led[led.ts < CUT].reset_index(drop=True)}
    out = tmp_path_factory.mktemp("world")
    write_world(truncated, CFG, out)
    return tables, truncated, out


@pytest.fixture(scope="module")
def requests(world):
    tables = world[0]
    view = PhoneView(tables, seed=0)
    # Every phone signal on for most users, so the comparison covers every feature; a few opted out.
    for i, uid in enumerate(view.traits):
        on = i % 7 != 0
        view.traits[uid] = Traits(on, on, on, i % 2 == 0, 1.0, money_watch=on, session_checks=i % 5 != 0)
    users = dict(zip(tables["users"].upi_id, tables["users"].user_id))
    led = tables["ledger"]
    led = led[(led.ts >= CUT) & led.from_upi.isin(users)].sort_values("ts", kind="stable")
    picked = pd.concat([led[led.label_is_scam], led[~led.label_is_scam].head(150)]).sort_values("ts", kind="stable")
    out = []
    for tx, ts, frm, to, amount, entry, scam in zip(picked.tx_id, picked.ts, picked.from_upi, picked.to_upi,
                                                    picked.amount, picked.entry_method, picked.label_is_scam):
        ctx, _ = view.context_at(users[frm], ts.timestamp(), to)
        says = view.payer_says(keyed_rng(0, "payment", tx), entry, amount, bool(scam), "digital_arrest", to)
        out.append(DecideRequest(request_id=tx, user_id=users[frm], payee_upi_id=to, amount_inr=float(amount),
                                 entry_method=entry, payer_says=says, ts=ts.to_pydatetime(), context=ctx))
    return out


def live_features(data_dir, reqs, monkeypatch):
    mock_app = create_mock(data_dir)
    mock = TestClient(mock_app)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_app), base_url="http://mock")
    monkeypatch.setattr(api.main, "DEADLINE_S", 60.0)  # compare values, not speed
    app = api.main.create_app(data_dir, intel_client=client, intel_cache_ttl_s=0, log_path=None,
                              evidence_async=False, intel_budget_s=60.0)
    seen = []
    app.state.score = lambda f: (seen.append(dict(f)), rule_scorer.score(f))[1]
    engine = TestClient(app)
    for req in reqs:
        mock.post("/sim/clock", json={"set": req.ts.isoformat()}).raise_for_status()
        r = engine.post("/v1/decide", json=req.model_dump(mode="json"))
        r.raise_for_status()
        assert not r.json()["fail_open"]
    return seen


def same(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        return a is not None and b is not None and math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)
    return a == b and type(a) is type(b)


def test_replay_matches_the_live_engine(world, requests, monkeypatch):
    tables, truncated, data_dir = world
    live = live_features(data_dir, requests, monkeypatch)

    history = PhoneView(truncated, seed=0)  # the bank's view: payments before the cut only
    engine = EngineReplay(Store.load(data_dir))
    replayed, statuses = [], []
    for req in requests:
        _, res, f = engine.step(req, bank_baseline(history, req.user_id, req.ts.timestamp()))
        replayed.append(f)
        statuses.append(res.status)

    assert len(live) == len(replayed) == len(requests)
    for req, a, b in zip(requests, live, replayed):
        assert a.keys() == b.keys()
        diff = {k: (a[k], b[k]) for k in a if not same(a[k], b[k])}
        assert not diff, f"{req.request_id}: live vs replay {diff}"

    # The comparison must have exercised the interesting paths, not just empty lookups.
    assert sum(s.get("bank") == "ok" for s in statuses) >= 20
    assert sum(s.get("bank") == "not_shared" for s in statuses) >= 5
    assert sum("caller_registry" in s for s in statuses) >= 1  # incoming SIM call from a stranger
    assert sum(r.context is None for r in requests) >= 3
    assert sum(f["payee_registry_listed"] is True for f in replayed) >= 1
    assert sum(r.context is not None and r.context.episode is not None for r in requests) >= 20
    assert sum(f["episode_state"] not in (None, 0) for f in replayed) >= 1  # an open episode
    assert sum(r.context is not None and r.context.session is not None for r in requests) >= 20
