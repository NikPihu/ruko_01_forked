"""sim_v2 guarantees. Run: PYTHONPATH=backend;ml;data python -m pytest data/sim_v2/tests -q"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from sim_v2 import validate
from sim_v2.core.config import load
from sim_v2.export import write
from sim_v2.run import build

ROOT = Path(__file__).resolve().parents[3]
quiet = lambda *_: None


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    cfg = load(users=400, days=14)
    tables = build(cfg, log=quiet)
    out = tmp_path_factory.mktemp("w")
    write(tables, cfg, out)
    return tables, out


def test_schema_and_content(world):
    results: list = []
    validate.schema(results, world[1])
    validate.content(results, world[1])
    assert all(results)


def test_deterministic_and_subset_stable():
    results: list = []
    validate.determinism(results)
    assert all(results)


def test_every_scam_payment_is_explained(world):
    t, _ = world
    scam = t["ledger"][t["ledger"].flow == "scam"]
    assert len(scam) > 0
    assert scam.cause_id.isin(set(t["decisions"].decision_id)).all()
    comply = t["decisions"].set_index("decision_id").loc[scam.cause_id.unique(), "outcome"]
    assert (comply == "comply").all()


def test_lookalikes_never_labelled_scam(world):
    led = world[0]["ledger"]
    look = led[led.scenario.notna()]
    assert len(look) > 0 and not look.label_is_scam.any()


def test_most_scam_money_reaches_unlisted_mules(world):
    t, _ = world
    rep = t["reports"]
    listed = rep[~rep.is_false & (rep.identifier_type == "upi_id")].groupby("identifier").listed_at.min()
    scam = t["ledger"][t["ledger"].flow == "scam"]
    assert (scam.to_upi.map(listed) < scam.ts).mean() < 0.3


def test_backend_engine_runs_on_sim_v2(world):
    from api.main import create_app as create_engine
    from intel_mock.app import create_app as create_mock
    _, d = world
    mock = create_mock(d)
    intel = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock), base_url="http://mock")
    eng = TestClient(create_engine(d, intel_client=intel, intel_cache_ttl_s=0, log_path=None, evidence_async=False))
    req = json.loads((ROOT / "contracts/examples/decide_request_meena.json").read_text())
    out = eng.post("/v1/decide", json=req).json()
    assert out["tier"] in ("T3", "T4") and out["playbook"] == "digital_arrest"
    mc = TestClient(mock)
    mule = mc.get("/banks/axis-bank/payee-risk/secure.settlement.desk@okaxis").json()["features"]
    assert mule["uniq_payers_7d"] >= 10 and mule["pass_through_7d"] > 0.6
    kir = mc.get("/banks/axis-bank/payee-risk/shreeganesh.kirana@okaxis").json()
    assert kir["features"]["repeat_payer_ratio_30d"] > 0.7 and kir["mulehunter"]["score"] < 0.3


def test_report_writes_html_and_docx(world):
    from sim_v2 import report
    html_path, docx_path = report.run(world[1], log=quiet)
    assert html_path.stat().st_size > 50_000 and docx_path.stat().st_size > 50_000
    assert "Why scams are hard to spot" in html_path.read_text(encoding="utf-8")


def test_twelve_playbooks_and_numbered_steps(world):
    cfg = load()
    assert len(cfg.playbooks) >= 12
    dec = world[0]["decisions"]
    victim = dec[dec.kind == "victim"]
    assert victim.step_no.notna().all() and (victim.step_no >= 1).all()
