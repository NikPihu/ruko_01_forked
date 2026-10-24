"""The trained server scorer (model/predict.py) must be a drop-in for api/rule_scorer.score."""
import time
import typing
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

import api.main
from api import rule_scorer
from features.build import FAMILY
from intel_mock.app import create_app as create_mock
from model import predict
from model.data import SERVER_FAMILIES
from model.reasons import NOT_A_REASON, REASON
from schema.events import ReasonCode
from sim.accounts import DEMO_KIRANA_UPI, DEMO_MEENA, DEMO_MULE_UPI
from sim.config import SimConfig
from sim.generate import build_world, write_world

pytestmark = pytest.mark.skipif(not predict.MODEL_PATH.exists(), reason="train first: python -m model.train")

CFG = SimConfig(seed=1, n_users=400, n_days=20, scam_rate=0.05)
NOW = CFG.end + timedelta(hours=10, minutes=40)
UNKNOWN_CALLER = "+919812345670"
REMOTE = {"remote_access_active": True, "remote_app_installed_min_ago": 25}
# The backend's demo context (test_decide.py MEENA_CONTEXT) ...
MEENA_BACKEND = {"call": {"active": True, "kind": "voip", "caller_number": UNKNOWN_CALLER,
                          "caller_in_contacts": False, "started_min_ago": 38}, "device": REMOTE, "lures": []}
# ... and what a real phone sends for a WhatsApp call: no number, contact status unknown.
MEENA_PHONE = {"call": {"active": True, "kind": "voip", "started_min_ago": 38}, "device": REMOTE, "lures": []}


def unknown_features(**known) -> dict:
    """A feature dict where nothing could be measured, plus the given values."""
    f = dict.fromkeys(FAMILY)
    f.update(amount_inr=1000.0, first_time_payee=True, entry_typed=True, attempts_72h=0, payee_in_run=True,
             trusted_payee=False, stage=0)
    f.update(known)
    return f


def test_reason_codes_cover_every_model_feature():
    codes = set(typing.get_args(ReasonCode))
    feats = {c for fam in ("C", "L", "P", "B") for c in SERVER_FAMILIES[fam]} - NOT_A_REASON
    assert feats <= set(REASON), feats - set(REASON)
    assert set(REASON.values()) <= codes


def test_same_shape_as_the_rules_engine():
    f = unknown_features()
    ml, rules = predict.score(f), rule_scorer.score(f)
    assert ml.keys() == rules.keys()
    assert set(ml["family_scores"]) == {"C", "L", "P", "B"}
    assert 0 <= ml["p_scam"] <= 1 and all(0 <= v <= 1 for v in ml["family_scores"].values())
    assert set(ml["reasons"]) <= set(typing.get_args(ReasonCode)) and len(ml["reasons"]) <= 4
    assert ml["model_version"] == predict.MODEL_VERSION == predict.load().version


NOISE = 0.002  # tree splits on noise move p_scam by ~1e-4; anything above this is a real rule-1 breach


@pytest.mark.parametrize("name,safe", [("remote_control", False), ("on_call", False), ("caller_unknown", False),
                                       ("payee_registry_listed", False), ("caller_registry_listed", False),
                                       ("story_mismatch", False), ("session_dictated", False), ("episode_state", 0)])
def test_unknown_never_scores_safer_than_measured_safe(name, safe):
    """CLAUDE.md rule 1, on a risky payment: not measuring a signal must not look calmer than
    measuring it calm."""
    base = unknown_features(amount_inr=95_000.0, amount_to_max_90d=6.0, payee_account_age_days=4.0,
                            payee_uniq_payers_6h=41, payee_repeat_ratio=0.0, payee_pass_through_24h=0.95,
                            payee_is_person=True, payee_holder_type="person")
    assert predict.score({**base, name: None})["p_scam"] >= predict.score({**base, name: safe})["p_scam"] - NOISE


def test_conditional_checks_count_only_when_positive():
    """"Not asked" must never be a safety signal (model.data.POSITIVE_ONLY)."""
    base = unknown_features(amount_inr=95_000.0, payee_holder_type="person", payee_account_age_days=4.0)
    for name in ("story_mismatch", "caller_registry_listed"):
        assert predict.score({**base, name: None})["p_scam"] == predict.score({**base, name: False})["p_scam"]


def test_fast_enough_for_the_decide_budget():
    f = unknown_features(on_call=True, voip_call=True, remote_control=True, amount_to_max_90d=6.0)
    predict.score(f)  # load once
    times = []
    for _ in range(200):
        t = time.perf_counter()
        predict.score(f)
        times.append(time.perf_counter() - t)
    assert sorted(times)[int(0.95 * len(times))] < 0.010  # p95 under 10 ms


# ---------- the demo stories, through the real engine with the ML scorer ----------

@pytest.fixture(scope="module")
def world(tmp_path_factory):
    out = tmp_path_factory.mktemp("data")
    tables = build_world(CFG)
    write_world(tables, CFG, out)
    return out, tables


@pytest.fixture()
def stack(world, monkeypatch):
    monkeypatch.setattr(api.main, "DEADLINE_S", 10.0)  # logic, not speed (CLAUDE.md, Tests)
    mock_app = create_mock(world[0])
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_app), base_url="http://mock")
    app = api.main.create_app(world[0], intel_client=client, intel_cache_ttl_s=0, log_path=None,
                              evidence_async=False, intel_budget_s=5.0)
    app.state.score = predict.score
    return TestClient(mock_app), TestClient(app)


def pump(mock, tables, n=40):
    acc = tables["accounts"]
    for p in acc[(acc.holder_type == "person") & ~acc.is_mule].upi_id[:n]:
        mock.post("/npci/pay", json={"from_upi": p, "to_upi": DEMO_MULE_UPI, "amount": 1500})
    cash_out = acc[acc.mule_kind == "cash_out"].upi_id.iloc[0]
    mock.post("/npci/pay", json={"from_upi": DEMO_MULE_UPI, "to_upi": cash_out, "amount": 54000})


def decide(engine, context, payee=DEMO_MULE_UPI, amount=95_000, entry="typed", says="government", user=DEMO_MEENA):
    body = {"request_id": "r_1", "user_id": user, "payee_upi_id": payee, "amount_inr": amount,
            "entry_method": entry, "ts": NOW.isoformat(), "context": context}
    if says:
        body["payer_says"] = says
    r = engine.post("/v1/decide", json=body)
    r.raise_for_status()
    return r.json()


@pytest.mark.parametrize("context", [MEENA_BACKEND, MEENA_PHONE], ids=["backend_context", "real_phone_context"])
def test_meena_digital_arrest_gets_paused(stack, world, context):
    mock, engine = stack
    pump(mock, world[1])
    r = decide(engine, context)
    assert r["tier"] in ("T3", "T4"), r
    assert "R2_remote_control" in r["reasons"] and "R3_mule_like_payee" in r["reasons"]
    assert "p_scam" not in r
    if context is MEENA_BACKEND:
        # The playbook comes from the rules engine's matcher, which needs caller_unknown. A real
        # phone sends null for a WhatsApp call, so it finds no playbook (ml/PLAN.md §12, backend).
        assert r["playbook"] == "digital_arrest"


def test_kirana_purchase_is_silent(stack, world):
    users = world[1]["users"]
    user = users[(users.region == "Pune") & (users.user_id != DEMO_MEENA)].user_id.iloc[0]
    r = decide(stack[1], None, payee=DEMO_KIRANA_UPI, amount=180, entry="qr", says=None, user=user)
    assert r["tier"] == "T0" and r["reasons"] == []


# ---- Payee guardrail (+pg1): hard payee evidence keeps the payee family at the rules' score ----

# The demo mule as the engine saw it on 2026-10-24 (pumped: 66 payers in 7 days, money loop, crowd).
# The payee model alone scores this 0.30: the training worlds' mules are all small.
BUSY_MULE = dict(payee_holder_type="person", payee_verified_merchant=False, payee_account_age_days=4.0,
                 payee_uniq_payers_6h=40, payee_uniq_payers_7d=66, payee_repeat_ratio=0.015,
                 payee_pass_through_24h=0.943, payee_median_hold_min=6.8, payee_registry_listed=False,
                 vpa_invalid=False, payee_crowd=True, payee_money_loop=True, payee_forwards_to_cashout=False,
                 payee_approved_suspect=False)


def _raw_payee(f: dict) -> float:
    """The payee family score without the guardrail."""
    m = predict.load()
    x = predict.encode_features(f)
    fam = m.families["P"]
    row = [[x.get(c, float("nan")) for c in fam.features]]
    import numpy as np
    return m.strength(fam.calibrated(np.array(row, dtype=float)))


def test_guardrail_lights_a_busy_mule_with_a_money_loop_and_crowd():
    f = unknown_features(**BUSY_MULE)
    assert _raw_payee(f) < predict.LIT              # the gap this guardrail closes
    s = predict.score(f)
    assert s["family_scores"]["P"] >= rule_scorer.score(f)["family_scores"]["P"] >= predict.LIT
    assert {"R3_mule_like_payee", "R11_ring_link"} <= set(s["reasons"])
    assert s["model_version"].endswith("+pg1")


@pytest.mark.parametrize("hard", [{"payee_registry_listed": True}, {"payee_approved_suspect": True},
                                  {"payee_money_loop": True, "payee_crowd": True}])
def test_each_kind_of_hard_evidence_lights_the_payee(hard):
    f = unknown_features(**hard)
    assert predict.hard_payee_evidence(f)
    assert predict.score(f)["family_scores"]["P"] >= rule_scorer.score(f)["family_scores"]["P"]
    assert predict.score(f)["family_scores"]["P"] >= predict.LIT


def test_soft_or_unknown_evidence_leaves_the_model_alone():
    for f in (unknown_features(), unknown_features(payee_crowd=True), unknown_features(payee_money_loop=True),
              unknown_features(**{**BUSY_MULE, "payee_money_loop": False})):
        assert predict.payee_floor(f) is None
        assert predict.score(f)["family_scores"]["P"] == round(_raw_payee(f), 3)


def test_guardrail_never_lowers_the_model():
    f = unknown_features(**{**BUSY_MULE, "payee_uniq_payers_7d": 20, "payee_crowd": True})
    assert predict.score(f)["family_scores"]["P"] >= round(_raw_payee(f), 3)


def test_batch_scoring_applies_the_same_guardrail():
    import pandas as pd
    from model.data import encode_frame
    rows = [unknown_features(**BUSY_MULE), unknown_features(), unknown_features(payee_approved_suspect=True)]
    df = pd.DataFrame(rows).assign(ts=pd.Timestamp("2026-10-24 12:00", tz="Asia/Kolkata"), amount=1000.0, payer_says=None)
    m = predict.load()
    p0, _ = m.score_frame(encode_frame(df))
    p, fam = m.score_frame(encode_frame(df), [predict.payee_floor(f) for f in rows])
    for i, f in enumerate(rows):
        assert fam["P"][i] == pytest.approx(predict.score(f)["family_scores"]["P"], abs=1e-3)
    assert p[0] > p0[0] and p[2] > p0[2] and p[1] == p0[1]
