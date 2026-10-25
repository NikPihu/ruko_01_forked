"""lgbm-0.3 training (model/train.py) and scoring (model/predict.py) on a small synthetic table:
both designs train, save, load and score a live feature dict with steps and a verdict."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from features.build import FAMILY
from model import predict, train
from model.data import STEP_FEATURES, VERDICT_FEATURES


def table(n: int = 4000, seed: int = 0) -> pd.DataFrame:
    """Scams: screen control on an unknown call to a young payee, or a dictated amount; honest
    payments sometimes have one of those alone."""
    rng = np.random.default_rng(seed)
    scam = rng.random(n) < 0.08
    remote = np.where(scam, rng.random(n) < 0.7, rng.random(n) < 0.01)
    young = np.where(scam, rng.random(n) < 0.8, rng.random(n) < 0.05)
    dictated = np.where(scam, rng.random(n) < 0.6, rng.random(n) < 0.01)
    d = {k: [None] * n for k in FAMILY}
    d |= {"on_call": remote | (rng.random(n) < 0.1), "caller_unknown": remote, "remote_control": remote,
          "payee_account_age_days": np.where(young, 5.0, 900.0), "session_dictated": dictated,
          "first_time_payee": scam | (rng.random(n) < 0.2), "amount_inr": np.where(scam, 40_000.0, 800.0),
          "stage": np.where(remote, 3, 0), "lure_tag": None, "payee_holder_type": "person", "trusted_payee": False}
    df = pd.DataFrame(d)
    df["tx_id"] = [f"t{i}" for i in range(n)]
    df["ts"] = pd.Timestamp("2026-10-01", tz="Asia/Kolkata") + pd.to_timedelta(np.arange(n), unit="min")
    df["user_id"] = [f"u{i % 500}" for i in range(n)]
    df["journey_id"] = [f"j{i % 300}" if s else None for i, s in enumerate(scam)]
    df["journey_pay_index"] = 0
    df["playbook"] = np.where(scam, "digital_arrest", None)
    df["label_is_scam"], df["weight"], df["amount"] = scam, 1.0, df["amount_inr"]
    df["payer_says"], df["entry_method"], df["has_context"], df["consent_sms"] = None, "typed", True, False
    df["dv_level"] = np.where(scam & (rng.random(n) < 0.5), "high", "low")
    df["dv_class"] = None
    for c in ("audit_age_band", "audit_language", "payee_merchant_kind", "payee_upi"):
        df[c] = "x"
    return df


@pytest.fixture(scope="module")
def tables(tmp_path_factory):
    out = tmp_path_factory.mktemp("v3")
    paths = []
    for i in range(2):
        p = out / f"t{i}.parquet"
        table(seed=i).to_parquet(p)
        paths.append(p)
    return paths


MEENA = {**dict.fromkeys(FAMILY), "on_call": True, "caller_unknown": True, "remote_control": True,
         "first_time_payee": True, "amount_inr": 40_000.0, "stage": 3, "trusted_payee": False,
         "steps": {"unknown_call": True, "remote_control": True, "new_payee": True}, "verdict": ("high", None)}


@pytest.mark.parametrize("arch", ["family", "single"])
def test_trains_saves_loads_and_scores(tables, tmp_path, arch):
    spec, cal, p = train.train(tables[:1], tables[1:], arch=arch)
    assert spec["version"] == "lgbm-0.3" and len(p) == len(cal)
    path = tmp_path / "server_model.json"
    path.write_text(json.dumps(spec))
    m = predict.load.__wrapped__(path)
    s = m.score(MEENA)
    assert set(s["family_scores"]) == {"C", "L", "P", "B"} and 0 <= s["p_scam"] <= 1
    if arch == "family":   # the single model credits the amount and gives screen control nothing (see below)
        assert "R2_remote_control" in s["reasons"]
    quiet = m.score({**dict.fromkeys(FAMILY), "amount_inr": 800.0, "first_time_payee": False, "stage": 0,
                     "trusted_payee": False, "steps": {}, "verdict": ("low", None)})
    assert quiet["p_scam"] < s["p_scam"]
    x = train.encode_table(tables[1], cache=False)
    pf, fam = m.score_frame(x)
    assert len(pf) == len(x) and set(fam) == {"C", "L", "P", "B"}


def test_family_design_lights_the_call_family_alone_and_never_weighs_evidence_negatively(tables):
    spec, _, _ = train.train(tables[:1], tables[1:], arch="family")
    assert min(spec["combiner"]["coef"]) >= 0
    assert set(spec["families"]["C"]["features"]) >= {c for c, f in STEP_FEATURES.items() if f == "C"}
    assert not set(VERDICT_FEATURES) & {c for f in spec["families"].values() for c in f["features"]}  # rule 5


def test_verdict_dropout_hides_the_phone_reading_too(tables):
    x = train.encode_table(tables[0], cache=False)
    hidden = x["verdict_hidden"].to_numpy(bool)
    assert 0.2 < hidden.mean() < 0.4
    assert x.loc[hidden, VERDICT_FEATURES].isna().all().all()
    assert x.loc[~hidden, "dv_level_high"].notna().all()


def test_why_family_models_a_single_model_takes_the_shortcut(tables, tmp_path):
    """In this table the amount alone separates the scams; a single model then lets screen control on an
    unknown call count for little, while the call family's own model must learn it."""
    fam, _, _ = train.train(tables[:1], tables[1:], arch="family")
    one, _, _ = train.train(tables[:1], tables[1:], arch="single")
    scores = {}
    for name, spec in (("family", fam), ("single", one)):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(spec))
        scores[name] = predict.load.__wrapped__(path).score(MEENA)["family_scores"]["C"]
    assert scores["family"] >= 0.5 > scores["single"]
