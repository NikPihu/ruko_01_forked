"""Train the server scorer lgbm-0.3 -> server_model.json

    PYTHONPATH=backend;ml;data python -m model.train --arch family --table ml/data/tables/v3/train_*.parquet --calib ml/data/tables/v3/calib_*.parquet --out ml/model/artifacts/v0

    PYTHONPATH=backend;ml;data python -m model.train --table ml/data/tables/v3/train_*.parquet --calib ml/data/tables/v3/calib_*.parquet --out ml/model/artifacts/v0

Plan v3 step 4. Inputs (model/data.py, the same encoding live in model/predict.py):
- every feature the engine computes (backend/features/build.py, its FAMILY map), incl. MuleHunter, the
  payment graph, campaigns, anchors, outflow;
- the phone's verdict converted: its family scores device_c/l/b, its level and scam class (one-hot);
- the journey's scam steps (contracts/steps.json), the server's reading merged with the phone's.
Not an input: the playbook search's similarity; it is fused afterwards (step 5), so the two stay
independent evidence.

Two designs (`--arch`), chosen on the test shards (plan v3 step 4):
- `family` (default): one LightGBM per family (C, L, P, B) on that family's inputs only (engine
  features by the FAMILY map, steps by their stage), each calibrated (isotonic) on the calibration
  tables, and a logistic combiner over the four calibrated families, the journey stage and the
  verdict's level, fitted on them too. Each family must learn from its own evidence: in the simulated
  worlds a dictated amount and a mule-like payee separate nearly every scam, and a single model then
  gives the call and screen control no weight, so a real digital arrest without session data scored
  ~0 (smoke test, 2026-10-24).
- `single`: one LightGBM over every input (the plan's first design), kept to compare.

Single design:
1. One LightGBM on the training tables, early stopping on the calibration tables (or, with no
   --calib, on a fifth of the users held out), then isotonic calibration of its output on them.
2. Family scores for the policy: each family's summed per-feature contribution (LightGBM
   pred_contrib, in log-odds) is how much that family's evidence multiplied the odds of a scam, LR;
   the score is LR / (LR + K): lit (>= 0.5) when the family alone makes a scam K times likelier.
   The verdict's level and class and the journey stage count in p_scam but in no family (rule 5).
3. The phone's verdict is hidden on a random VERDICT_DROPOUT share of rows (its scores, level, class
   and its step reading), so an app that sends raw signals and no verdict is still scored right.
Ground truth is used only as the training label. Encoded tables are cached next to the tables
(`<dir>/enc/<name>.parquet`), so a retrain does not recompute the steps.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import GroupShuffleSplit

from model.data import (SERVER_FAMILIES, STAGE_FEATURES, STEP_FEATURES, VERDICT_FEATURES, encode_frame)
from model.metrics import evaluate, summary_line
from model.reasons import REASON_V3

VERSION = "lgbm-0.3"
FAMILIES = ("C", "L", "P", "B")
FAMILY_K = 10.0     # a family is lit when its evidence alone makes a scam >= 10x likelier
PARAMS = dict(objective="binary", learning_rate=0.05, num_leaves=31, min_data_in_leaf=50,
              feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, verbose=-1)
MAX_ROUNDS = 3000
EARLY_STOP = 100
CLIP = 1e-4
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
VERDICT_DROPOUT = 0.3
# What the evaluation and the reports need besides the inputs.
META = ["tx_id", "ts", "user_id", "journey_id", "journey_pay_index", "playbook", "label_is_scam", "weight", "amount",
        "audit_age_band", "audit_language", "payee_merchant_kind", "payee_upi"]


def logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, CLIP, 1 - CLIP)
    return np.log(p / (1 - p))


def strength(p: np.ndarray | float, prior: float, k: float = FAMILY_K) -> np.ndarray | float:
    """Family score from a calibrated family probability: its likelihood ratio, squashed as LR / (LR + K)
    (the on-device model's family scores; the server's come from contributions, family_strength)."""
    p = np.clip(p, CLIP, 1 - CLIP)
    lr = (p / (1 - p)) / (prior / (1 - prior))
    return lr / (lr + k)


def family_strength(log_lr: np.ndarray | float, k: float = FAMILY_K) -> np.ndarray | float:
    """Family score from the family's summed contribution (log-odds): LR / (LR + K)."""
    return 1 / (1 + k * np.exp(-np.clip(log_lr, -50, 50)))


def feature_families() -> dict[str, str | None]:
    """Every model input and the family it speaks for (None: p_scam only, no family)."""
    out: dict[str, str | None] = {c: f for f in FAMILIES for c in SERVER_FAMILIES[f]}
    out |= dict.fromkeys(STAGE_FEATURES)
    out |= dict.fromkeys(VERDICT_FEATURES)
    out |= STEP_FEATURES
    return out


def _seed_of(name: str, seed: int) -> int:
    return int(hashlib.sha256(f"{name}:{seed}".encode()).hexdigest()[:8], 16)


def encode_table(path: Path, seed: int = 0, cache: bool = True) -> pd.DataFrame:
    """One replayed table -> its model inputs (float32) and META columns, with verdict dropout drawn
    from the table's own seed (so a cached encoding is the same as a fresh one)."""
    cols = list(feature_families())
    enc = path.parent / "enc" / f"{path.stem}.s{seed}.parquet"
    if cache and enc.exists() and enc.stat().st_mtime >= path.stat().st_mtime:
        d = pd.read_parquet(enc)
        if set(cols) | set(META) <= set(d.columns):
            return d
    df = pd.read_parquet(path).reset_index(drop=True)
    hide = np.random.default_rng(_seed_of(path.stem, seed)).random(len(df)) < VERDICT_DROPOUT
    x = encode_frame(df, hide_verdict=hide)
    out = pd.concat([x.reindex(columns=cols).astype("float32"),
                     df[[c for c in META if c in df.columns]]], axis=1)
    out["verdict_hidden"] = hide
    if cache:
        enc.parent.mkdir(exist_ok=True)
        out.to_parquet(enc)
    return out


def load_encoded(tables: list[Path], seed: int = 0, tag: str = "w") -> pd.DataFrame:
    """Several tables; user and journey ids are prefixed per table (two worlds reuse ids)."""
    parts = []
    for i, t in enumerate(tables):
        d = encode_table(Path(t), seed)
        d["user_id"] = f"{tag}{i}:" + d["user_id"].astype(str)
        if "journey_id" in d:
            d["journey_id"] = d["journey_id"].map(lambda j, i=i: None if pd.isna(j) else f"{tag}{i}:{j}")
        parts.append(d)
    return pd.concat(parts, ignore_index=True) if len(parts) > 1 else parts[0]


def family_contrib(booster: lgb.Booster, x: pd.DataFrame, fams: dict[str, str | None],
                   chunk: int = 200_000) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """({family: summed contribution}, raw log-odds) for every row, in chunks (pred_contrib is wide)."""
    feats = booster.feature_name()
    idx = {f: [i for i, c in enumerate(feats) if fams.get(c) == f] for f in FAMILIES}
    out = {f: np.empty(len(x)) for f in FAMILIES}
    raw = np.empty(len(x))
    for a in range(0, len(x), chunk):
        c = booster.predict(x[feats].iloc[a:a + chunk], pred_contrib=True)
        for f in FAMILIES:
            out[f][a:a + chunk] = c[:, idx[f]].sum(axis=1)
        raw[a:a + chunk] = c.sum(axis=1)
    return out, raw


def _split(tables: list[Path], calib: list[Path] | None, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = load_encoded([Path(t) for t in tables], seed, "t")
    if calib:
        return df, load_encoded([Path(t) for t in calib], seed, "c")
    tr_i, ca_i = next(GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=seed).split(df, groups=df["user_id"]))
    return df.iloc[tr_i].reset_index(drop=True), df.iloc[ca_i].reset_index(drop=True)


COMBINER_EXTRA = ("dv_level_medium", "dv_level_high")   # the phone's verdict level; 0 when no verdict


def combiner_inputs(cal: dict[str, np.ndarray], stage: np.ndarray, extra: np.ndarray | None = None) -> np.ndarray:
    cols = [logit(cal[f]) for f in FAMILIES] + [np.nan_to_num(stage, nan=0.0)]
    if extra is not None:
        cols += [np.nan_to_num(extra[:, i], nan=0.0) for i in range(extra.shape[1])]
    return np.column_stack(cols)


def fit_combiner(z: np.ndarray, y: np.ndarray, w: np.ndarray, l2: float = 1.0) -> tuple[np.ndarray, float]:
    """Weighted logistic regression whose weights are all >= 0: more evidence from a family (or a
    higher stage or verdict level) never lowers p_scam. An unconstrained fit gave the call family a
    negative weight in these worlds (C and the payee move together in every scam), which would make a
    stronger call signal look safer."""
    from scipy.optimize import minimize
    sw = w / w.mean()

    def loss(theta):
        b, c = theta[0], theta[1:]
        m = b + z @ c
        p = 1 / (1 + np.exp(-m))
        nll = np.sum(sw * (np.logaddexp(0, m) - y * m)) / len(y) + l2 * np.sum(c ** 2) / (2 * len(y))
        g = sw * (p - y) / len(y)
        return nll, np.concatenate([[g.sum()], z.T @ g + l2 * c / len(y)])

    theta0 = np.zeros(z.shape[1] + 1)
    bounds = [(None, None)] + [(0.0, None)] * z.shape[1]
    r = minimize(loss, theta0, jac=True, method="L-BFGS-B", bounds=bounds)
    return r.x[1:], float(r.x[0])


def train_family(tables: list[Path], calib: list[Path] | None = None, seed: int = 0) -> tuple[dict, pd.DataFrame, np.ndarray]:
    """Four family models on the training tables; isotonic + combiner on the calibration tables."""
    fams = feature_families()
    df, cal = _split(tables, calib, seed)
    y, w = df["label_is_scam"].to_numpy(bool), df["weight"].to_numpy(float)
    yc, wc = cal["label_is_scam"].to_numpy(bool), cal["weight"].to_numpy(float)
    prior = float(w[y].sum() / w.sum())
    families, calp = {}, {}
    for f in FAMILIES:
        cols = [c for c, fam in fams.items() if fam == f]
        dtr = lgb.Dataset(df[cols], y, weight=w)
        dca = lgb.Dataset(cal[cols], yc, weight=wc, reference=dtr)
        b = lgb.train({**PARAMS, "seed": seed}, dtr, num_boost_round=MAX_ROUNDS, valid_sets=[dca],
                      callbacks=[lgb.early_stopping(EARLY_STOP, verbose=False)])
        raw = b.predict(cal[cols], num_iteration=b.best_iteration)
        iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(raw, yc, sample_weight=wc)
        calp[f] = iso.predict(raw)
        families[f] = {"features": cols, "booster": b.model_to_string(num_iteration=b.best_iteration),
                       "rounds": int(b.best_iteration), "iso_x": iso.X_thresholds_.tolist(), "iso_y": iso.y_thresholds_.tolist()}
    stage = cal[STAGE_FEATURES[0]].to_numpy(float)
    z = combiner_inputs(calp, stage, cal[list(COMBINER_EXTRA)].to_numpy(float))
    coef, intercept = fit_combiner(z, yc.astype(float), wc)
    p_cal = 1 / (1 + np.exp(-(intercept + z @ coef)))
    lit = {f: strength(calp[f], prior) >= 0.5 for f in FAMILIES}
    model = {
        "version": VERSION, "kind": "family", "trained_on": ";".join(str(t) for t in tables),
        "calibrated_on": ";".join(str(t) for t in calib) if calib else "held-out users",
        "rows": int(len(df)), "scam_payments": int(y.sum()), "scam_journeys": int(df.loc[y, "journey_id"].nunique()),
        "calib_rows": int(len(cal)), "calib_scam_payments": int(yc.sum()),
        "prior": prior, "family_k": FAMILY_K, "verdict_dropout": VERDICT_DROPOUT, "params": PARAMS,
        "families": families,
        "combiner": {"inputs": [*FAMILIES, "stage", *COMBINER_EXTRA], "coef": coef.tolist(), "intercept": intercept},
        "reasons": {k: v for k, v in REASON_V3.items() if k in fams},
        "calib": {"lit_share_on_scam": {f: float(lit[f][yc].mean()) for f in FAMILIES},
                  "lit_share_on_legit": {f: float(np.average(lit[f][~yc], weights=wc[~yc])) for f in FAMILIES}},
    }
    return model, cal, p_cal


def train(tables: Path | list[Path], calib: list[Path] | None = None, seed: int = 0,
          arch: str = "family") -> tuple[dict, pd.DataFrame, np.ndarray]:
    """(model spec, calibration rows, calibrated p_scam on them)."""
    tables = [tables] if isinstance(tables, (str, Path)) else list(tables)
    if arch == "family":
        return train_family(tables, calib, seed)
    fams = feature_families()
    feats = list(fams)
    df, cal = _split(tables, calib, seed)
    y, w = df["label_is_scam"].to_numpy(bool), df["weight"].to_numpy(float)
    yc, wc = cal["label_is_scam"].to_numpy(bool), cal["weight"].to_numpy(float)
    dtrain = lgb.Dataset(df[feats], y, weight=w, free_raw_data=True)
    dcal = lgb.Dataset(cal[feats], yc, weight=wc, reference=dtrain)
    booster = lgb.train({**PARAMS, "seed": seed}, dtrain, num_boost_round=MAX_ROUNDS, valid_sets=[dcal],
                        callbacks=[lgb.early_stopping(EARLY_STOP, verbose=False)])
    raw_cal = booster.predict(cal[feats], num_iteration=booster.best_iteration)
    iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(raw_cal, yc, sample_weight=wc)
    p_cal = iso.predict(raw_cal)

    booster_str = booster.model_to_string(num_iteration=booster.best_iteration)
    final = lgb.Booster(model_str=booster_str)
    contrib, _ = family_contrib(final, cal, fams)
    lit = {f: family_strength(contrib[f]) >= 0.5 for f in FAMILIES}
    prior = float(w[y].sum() / w.sum())
    gain = dict(zip(final.feature_name(), final.feature_importance("gain")))
    model = {
        "version": VERSION, "kind": "single", "trained_on": ";".join(str(t) for t in tables),
        "calibrated_on": ";".join(str(t) for t in calib) if calib else "held-out users",
        "rows": int(len(df)), "scam_payments": int(y.sum()), "scam_journeys": int(df.loc[y, "journey_id"].nunique()),
        "calib_rows": int(len(cal)), "calib_scam_payments": int(yc.sum()),
        "prior": prior, "family_k": FAMILY_K, "verdict_dropout": VERDICT_DROPOUT,
        "rounds": int(booster.best_iteration), "params": PARAMS,
        "features": feats, "families": fams, "booster": booster_str,
        "iso_x": iso.X_thresholds_.tolist(), "iso_y": iso.y_thresholds_.tolist(),
        "reasons": {k: v for k, v in REASON_V3.items() if k in fams},
        "calib": {"lit_share_on_scam": {f: float(lit[f][yc].mean()) for f in FAMILIES},
                  "lit_share_on_legit": {f: float(np.average(lit[f][~yc], weights=wc[~yc])) for f in FAMILIES},
                  "top_gain": {k: round(float(v), 1) for k, v in sorted(gain.items(), key=lambda kv: -kv[1])[:25]}},
    }
    return model, cal, p_cal


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--table", type=Path, nargs="+", required=True, help="one or more replayed training tables")
    p.add_argument("--calib", type=Path, nargs="*", default=None,
                   help="calibration tables (early stopping, isotonic); default a fifth of the users")
    p.add_argument("--out", type=Path, default=ARTIFACTS / "v0")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--arch", choices=("family", "single"), default="family")
    a = p.parse_args()
    t0 = time.perf_counter()
    model, cal, p_cal = train(a.table, a.calib, a.seed, a.arch)
    m = evaluate(cal, p_cal)
    model["calib"]["metrics"] = m
    a.out.mkdir(parents=True, exist_ok=True)
    path = a.out / "server_model.json"
    path.write_text(json.dumps(model, separators=(",", ":"), default=lambda v: None if isinstance(v, float) and math.isnan(v) else v))
    print(summary_line(f"{VERSION} calibration rows", m))
    print(f"{model.get('rounds') or {f: v['rounds'] for f, v in model['families'].items()}} rounds | lit on scam payments:",
          {f: f"{100 * v:.0f}%" for f, v in model["calib"]["lit_share_on_scam"].items()},
          "| on legit:", {f: f"{100 * v:.1f}%" for f, v in model["calib"]["lit_share_on_legit"].items()})
    print(f"-> {path} ({path.stat().st_size / 1024:.0f} KB) in {time.perf_counter() - t0:.0f}s")


if __name__ == "__main__":
    main()
