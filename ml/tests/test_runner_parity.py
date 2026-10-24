"""The red-team runner's live engine must see what the training replay sees, payment for payment.

Nikunj's runner (synthetic_playbook/interface_script) sends a sim_v2 world to the real engine and
its mock services. Those services answer as of their clock; until the runner moved it to each
message's time they answered as of the world's last day, so payee signals (account age, payers,
MuleHunter, pass-through, registry listings from the future) differed on most payments and every
red-team verdict and live check measured a different engine input than the model trains on.
"""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "synthetic_playbook"))
pytest.importorskip("interface_script")

from dataset.replay import EngineReplay  # noqa: E402
from features.user_baseline import Baselines  # noqa: E402
from intel_mock.store import Store  # noqa: E402
from interface_script import records  # noqa: E402
from interface_script.server import open_local  # noqa: E402
from schema.events import DecideRequest  # noqa: E402


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    from sim_v2.core.config import load
    from sim_v2.export import write
    from sim_v2.run import build
    cfg = load(users=60, days=8, seed=4, world="train", victim_rate={"train": 1.0, "eval": 0.01})
    out = tmp_path_factory.mktemp("sim_v2_world")
    write(build(cfg, log=lambda *a: None), cfg, out)
    return out


def same(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        return a is not None and b is not None and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return a == b


def test_the_runner_engine_sees_the_replays_features(world):
    stream = list(records.stream(world, seed=0, warmup_days=2, normal_sample=1.0))
    srv = open_local(world, "rules")
    app = srv._c.app
    live, cur = {}, {}
    score = app.state.score
    app.state.score = lambda f: (live.__setitem__(cur["id"], dict(f)), score(f))[1]
    import api.main
    old = api.main.DEADLINE_S
    api.main.DEADLINE_S = 60.0                      # compare values, not speed
    try:
        for rec in stream:
            if rec["body"].get("ts"):
                srv.clock(rec["body"]["ts"])
            if rec["kind"] == "episode":
                srv.post("/v1/episode", rec["body"])
            elif rec["kind"] == "pay":
                cur["id"] = rec["body"]["request_id"]
                srv.post("/v1/decide", rec["body"])
                b = rec["body"]
                srv.post("/v1/payment/outcome", {"request_id": b["request_id"], "user_id": b["user_id"],
                                                 "payee_upi_id": b["payee_upi_id"], "amount_inr": b["amount_inr"],
                                                 "status": "completed", "ts": b["ts"]})
    finally:
        api.main.DEADLINE_S = old
        srv.close()

    engine, baselines = EngineReplay(Store.load(world), world), Baselines.from_data(world)
    diffs, n = {}, 0
    for rec in stream:
        if rec["kind"] == "episode":
            engine.episode_event(rec["body"])
        elif rec["kind"] == "pay":
            req = DecideRequest(**rec["body"])
            _, _, f = engine.step(req, baselines.get(req.user_id, at=req.ts))
            engine.outcome(req)
            n += 1
            for k, v in f.items():
                if not same(v, live[req.request_id].get(k)):
                    diffs.setdefault(k, 0)
                    diffs[k] += 1
    assert n >= 200
    assert not diffs, f"live runner vs replay, payments that differ per feature: {diffs}"
