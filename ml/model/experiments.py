"""Side-by-side comparison of feature sets on one replayed table (the deck's key ablation).

    PYTHONPATH=backend;ml;data python -m model.experiments --table ml/data/tables/dev.parquet

Every row is scored by a model that never saw that payer (5 folds grouped by user). All rows use
one LightGBM setup, so differences come from the features, not the tuning. The current engine
(`api/rule_scorer`, rules-0.2) is scored on the same rows for reference.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

from api import rule_scorer
from features.build import FAMILY
from model.data import TODAY, TXN_ONLY, device_feature_list, encode_frame, server_features
from model.metrics import evaluate, summary_line

LISTS = ["payee_registry_listed", "caller_registry_listed", "payee_fri_level", "caller_fri_level"]
PARAMS = dict(objective="binary", learning_rate=0.05, num_leaves=15, min_data_in_leaf=20,
              feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, verbose=-1)
ROUNDS = 300


def feature_sets() -> dict[str, list[str]]:
    srv = server_features()
    return {
        # World check: in a realistic world this scores near the base rate (PR-AUC ~ prevalence).
        "giveaways (round, typed, hour, asked)": ["audit_round_100", "entry_typed", "hour_ist", "audit_payer_asked"],
        "txn only (bank FRM)": TXN_ONLY,
        "today (FRM + lists)": TODAY,
        "RUKO server, lists blind": [f for f in srv if f not in LISTS],
        "RUKO server": srv,
        "device only": device_feature_list(),
        "RUKO server + device": srv + device_feature_list(),
    }


def oof_scores(x: pd.DataFrame, y: np.ndarray, w: np.ndarray, groups: np.ndarray, folds: int = 5,
               seed: int = 0) -> np.ndarray:
    out = np.zeros(len(y))
    for k, (tr, te) in enumerate(GroupKFold(n_splits=folds).split(x, y, groups)):
        booster = lgb.train({**PARAMS, "seed": seed + k}, lgb.Dataset(x.iloc[tr], y[tr], weight=w[tr]),
                            num_boost_round=ROUNDS)
        out[te] = booster.predict(x.iloc[te])
    return out


def rules_scores(df: pd.DataFrame) -> np.ndarray:
    keys = list(FAMILY)
    raw = df[keys].astype(object).where(df[keys].notna(), None)
    return np.array([rule_scorer.score(dict(zip(keys, row)))["p_scam"] for row in raw.itertuples(index=False)])


def run(table: Path, per_1000: float = 5.0) -> dict:
    df = pd.read_parquet(table)
    x = encode_frame(df)
    y = df["label_is_scam"].to_numpy(bool)
    w = df["weight"].to_numpy(float)
    groups = df["user_id"].to_numpy()
    results = {"table": str(table), "alert_budget_per_1000": per_1000}
    t0 = time.perf_counter()
    results["rules-0.2 (current engine)"] = evaluate(df, rules_scores(df), per_1000)
    print(summary_line("rules-0.2 (current engine)", results["rules-0.2 (current engine)"]), flush=True)
    for name, cols in feature_sets().items():
        missing = [c for c in cols if c not in x.columns]
        if missing:
            raise KeyError(f"{name}: no column {missing}")
        m = evaluate(df, oof_scores(x[cols], y, w, groups), per_1000)
        m["n_features"] = len(cols)
        results[name] = m
        print(summary_line(name, m), flush=True)
    print(f"({time.perf_counter() - t0:.0f}s)")
    return results


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--table", type=Path, required=True)
    p.add_argument("--budget", type=float, default=5.0, help="interruptions per 1,000 legit payments")
    p.add_argument("--out", type=Path, default=None)
    a = p.parse_args()
    res = run(a.table, a.budget)
    out = a.out or Path(__file__).resolve().parents[1] / "runs" / f"experiments_{a.table.stem}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, default=lambda v: None if isinstance(v, float) and math.isnan(v) else v))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
