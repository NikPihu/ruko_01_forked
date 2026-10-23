"""Fit sim_v1's amount and P2P/P2M knobs to the real NPCI anchors (Bayesian optimisation, Optuna).

    PYTHONPATH=backend:ml:data python -m sim_v1.calibrate --trials 150
    -> data/sim_v1/calibrated.json   (config.load() picks it up)

Fast because it samples payments the way generate.normal_life() does, without building a world.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import optuna

from sim_v1.config import HERE, PERSONAS, P2P_TXN_CAP
from sim_v1.generate import lognormal_mix

ANCHORS = json.loads((HERE.parent / "eval" / "realism" / "npci_anchors.json").read_text())["targets"]
KEYS = ["p2m_share_of_volume", "p2m_share_of_value", "avg_ticket_p2p_inr", "avg_ticket_p2m_inr",
        "p2m_share_below_500", "p2p_share_below_500"]


def sample(params: dict, p2m_shift: float, n: int = 200_000, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    names = list(PERSONAS)
    # payments come from personas in proportion to share x activity
    w = np.array([PERSONAS[p][0] * PERSONAS[p][1] for p in names])
    who = rng.choice(len(names), n, p=w / w.sum())
    p2m_p = np.clip(np.array([PERSONAS[p][2] for p in names])[who] + p2m_shift, 0, 1)
    mult = np.array([PERSONAS[p][3] for p in names])[who]
    is_m = rng.random(n) < p2m_p
    a_m = lognormal_mix(rng, n, params["p2m_bulk_median"], params["p2m_bulk_sigma"], params["p2m_tail_median"],
                        params["p2m_tail_sigma"], params["p2m_tail_weight"])
    a_p = lognormal_mix(rng, n, params["p2p_bulk_median"], params["p2p_bulk_sigma"], params["p2p_tail_median"],
                        params["p2p_tail_sigma"], params["p2p_tail_weight"])
    a = np.minimum(np.where(is_m, a_m, a_p) * mult, P2P_TXN_CAP)
    m, p = a[is_m], a[~is_m]
    return {"p2m_share_of_volume": is_m.mean(), "p2m_share_of_value": m.sum() / a.sum(),
            "avg_ticket_p2p_inr": p.mean(), "avg_ticket_p2m_inr": m.mean(),
            "p2m_share_below_500": (m < 500).mean(), "p2p_share_below_500": (p < 500).mean()}


def loss(got: dict) -> float:
    err = 0.0
    for k in KEYS:
        a = ANCHORS[k]
        e = (got[k] - a["value"]) / a["value"] if "tolerance_rel" in a else (got[k] - a["value"])
        tol = a.get("tolerance_rel", a.get("tolerance"))
        err += (e / tol) ** 2  # 1.0 = exactly at the edge of tolerance
    return err


def objective(trial: optuna.Trial) -> float:
    p = {"p2m_bulk_median": trial.suggest_float("p2m_bulk_median", 50, 400, log=True),
         "p2m_bulk_sigma": trial.suggest_float("p2m_bulk_sigma", 0.5, 1.5),
         "p2m_tail_median": trial.suggest_float("p2m_tail_median", 800, 10000, log=True),
         "p2m_tail_sigma": trial.suggest_float("p2m_tail_sigma", 0.4, 1.4),
         "p2m_tail_weight": trial.suggest_float("p2m_tail_weight", 0.01, 0.25),
         "p2p_bulk_median": trial.suggest_float("p2p_bulk_median", 50, 800, log=True),
         "p2p_bulk_sigma": trial.suggest_float("p2p_bulk_sigma", 0.5, 1.5),
         "p2p_tail_median": trial.suggest_float("p2p_tail_median", 2000, 30000, log=True),
         "p2p_tail_sigma": trial.suggest_float("p2p_tail_sigma", 0.4, 1.4),
         "p2p_tail_weight": trial.suggest_float("p2p_tail_weight", 0.1, 0.6)}
    shift = trial.suggest_float("p2m_shift", -0.15, 0.15)
    return loss(sample(p, shift, n=60_000))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=150)
    a = ap.parse_args()
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(sampler=optuna.samplers.TPESampler(seed=7))
    study.optimize(objective, n_trials=a.trials)
    best = dict(study.best_params)
    got = sample(best, best["p2m_shift"])
    out = {"params": {k: round(v, 4) for k, v in best.items()},
           "loss": round(loss(got), 4), "achieved": {k: round(float(v), 4) for k, v in got.items()},
           "targets": {k: ANCHORS[k]["value"] for k in KEYS}}
    (HERE / "calibrated.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
