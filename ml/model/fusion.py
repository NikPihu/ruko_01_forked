"""Fit the fused threat (backend/api/threat.py) on the calibration shards -> artifacts/v0/fusion.json

    PYTHONPATH=backend;ml;data python -m model.fusion --table ml/data/tables/v3/calib_*.parquet

1. Score every calibration payment with the trained model (p_lgbm, the payee guardrail on) and run the
   playbook search on its steps (the best playbook's similarity).
2. p_playbook: isotonic regression of "scam?" on the similarity, over payments with a match.
3. Fusion form: noisy-OR, or a logistic fit over (logit p_lgbm, logit p_playbook, their product) when
   it has a lower weighted log-loss.
4. Tier thresholds for policy.yaml `fused.tiers`: the lowest threat bars that keep honest payments
   at T1+ <= 20, T2+ <= 1.5, T3+ <= 0.5 per 1,000 (weighted), T4 = T3's bar or higher (it needs an
   intel hit too); then checked through the real policy (guardrails, alert budget) in time order.
   Printed for policy.yaml; the artifact holds only the calibration and the form (rule 6).
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from api import playbook_search as ps
from api import threat as threat_mod
from features.steps import STEP_IDS
from model import predict
from model.data import encode_frame, step_col

OUT = Path(__file__).resolve().parent / "artifacts" / "v0" / "fusion.json"
BUDGET = {"T1": 20.0, "T2": 1.5, "T3": 0.5}         # honest payments at this tier or above, per 1,000


def best_matches(x: pd.DataFrame) -> tuple[np.ndarray, list[str | None]]:
    """The best playbook's similarity and name for every row of encode_frame output."""
    cols = [step_col(s) for s in STEP_IDS]
    sims, names = np.zeros(len(x)), []
    for i, rec in enumerate(x[cols].to_numpy()):
        seen = {s: (None if math.isnan(v) else bool(v)) for s, v in zip(STEP_IDS, rec)}
        hit = ps.search(seen, ps.PLAYBOOKS, top=1)
        sims[i] = hit[0]["similarity"] if hit else 0.0
        names.append(hit[0]["name"] if hit else None)
    return sims, names


def model_scores(df: pd.DataFrame, feats: list[dict], model) -> tuple[pd.DataFrame, np.ndarray, dict]:
    x = encode_frame(df)
    p, fam = model.score_frame(x, [predict.payee_floor(f) for f in feats])
    return x, p, fam


def _wll(p: np.ndarray, y: np.ndarray, w: np.ndarray) -> float:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.average(y * np.log(p) + (1 - y) * np.log(1 - p), weights=w))


def fit(df: pd.DataFrame, feats: list[dict], model) -> tuple[dict, np.ndarray, np.ndarray, dict]:
    """(fusion spec, threat per row, p_lgbm per row, family scores per row)."""
    from model.train import fit_combiner, logit
    y, w = df["label_is_scam"].to_numpy(bool), df["weight"].to_numpy(float)
    x, p_lgbm, fam = model_scores(df, feats, model)
    sims, names = best_matches(x)
    m = sims > 0
    iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(sims[m], y[m], sample_weight=w[m])
    spec = {"model_version": model.version, "playbooks": ps.SOURCE,
            "playbook_iso": {"x": iso.X_thresholds_.tolist(), "y": iso.y_thresholds_.tolist()}, "form": "noisy_or"}
    fz = threat_mod.Fusion.from_spec(spec)
    pp = np.array([fz.p_playbook(s) for s in sims])
    noisy = np.maximum.reduce([1 - (1 - p_lgbm) * (1 - pp), p_lgbm, pp])
    a, b = logit(p_lgbm), logit(pp)
    z = np.column_stack([a, b, a * b])
    # fit_combiner keeps weights >= 0; the product term may need either sign, so fit it on -/+ copies
    coef, intercept = fit_combiner(np.column_stack([z, -z[:, 2]]), y.astype(float), w)
    coef = [coef[0], coef[1], coef[2] - coef[3]]
    lin = 1 / (1 + np.exp(-(intercept + z @ np.array(coef))))
    logistic = np.maximum.reduce([lin, p_lgbm, pp])
    ll = {"noisy_or": _wll(noisy, y, w), "logistic": _wll(logistic, y, w), "lgbm_only": _wll(p_lgbm, y, w)}
    if ll["logistic"] < ll["noisy_or"]:
        spec |= {"form": "logistic", "coef": coef, "intercept": float(intercept)}
        t = logistic
    else:
        t = noisy
    spec["calib"] = {"log_loss": ll, "rows": int(len(df)), "scam_payments": int(y.sum()),
                     "with_a_match": {"scam": float(m[y].mean()), "honest": float(np.average(m[~y], weights=w[~y]))}}
    spec["calib"]["best_playbook_on_scam"] = pd.Series(names)[y].fillna("-").value_counts().to_dict()
    return spec, t, p_lgbm, fam


def thresholds(t: np.ndarray, y: np.ndarray, w: np.ndarray) -> dict[str, float]:
    """The lowest bar per tier whose honest rate stays within BUDGET (weighted, per 1,000)."""
    honest_t, honest_w = t[~y], w[~y]
    order = np.argsort(-honest_t)
    cum = np.cumsum(honest_w[order]) / honest_w.sum() * 1000
    out = {}
    for tier, per_1000 in BUDGET.items():
        k = np.searchsorted(cum, per_1000, side="right")       # this many top honest payments fit the budget
        bar = honest_t[order][k] if k < len(order) else 0.0
        out[tier] = float(min(0.999, np.nextafter(bar, 1.0)))    # strictly above the first honest one over
    out["T2"] = max(out["T2"], out["T1"])
    out["T3"] = max(out["T3"], out["T2"])
    out["T4"] = out["T3"]
    return {k: round(v, 4) for k, v in out.items()}


def main() -> None:
    from model.evaluate import raw_features, read_tables, tier_metrics, tiers
    from api.policy import Policy
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--table", type=Path, nargs="+", required=True, help="calibration tables")
    p.add_argument("--model", type=Path, default=None)
    p.add_argument("--out", type=Path, default=OUT)
    a = p.parse_args()
    model = predict.load(a.model or predict.MODEL_PATH)
    df = read_tables(a.table)
    feats = raw_features(df)
    spec, t, p_lgbm, fam = fit(df, feats, model)
    y, w = df["label_is_scam"].to_numpy(bool), df["weight"].to_numpy(float)
    bars = thresholds(t, y, w)
    spec["proposed_tiers"] = bars
    cfg = Policy().cfg
    cfg["fused"] = {**cfg["fused"], "tiers": bars}
    x_scores = [{"p_scam": float(p_lgbm[i]), "family_scores": {k: float(v[i]) for k, v in fam.items()},
                 "threat": float(t[i]), "playbook": None} for i in range(len(df))]
    spec["calib"]["policy"] = tier_metrics(df, tiers(df, feats, x_scores, cfg))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(spec, indent=1), encoding="utf-8")
    pol = spec["calib"]["policy"]
    print(f"form {spec['form']} | log-loss {spec['calib']['log_loss']}")
    print(f"policy.yaml fused.tiers: {bars}")
    print(f"calib through the policy: scam payments interrupted {100 * pol['scam_payments_interrupted']:.1f}%, "
          f"honest interruptions/1k {pol['legit_interruptions_per_1000']:.2f}, tiers {pol['tiers']}")
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
