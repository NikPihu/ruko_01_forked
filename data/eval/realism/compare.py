"""Data realism check: team simulator vs old prototype sim vs real data (see FINDINGS.md).

    PYTHONPATH=backend:ml:data python -m eval.realism.compare --team data/
    -> data/eval/realism/results.json

--team is a folder written by `python -m sim.generate` (the full Parquet tables, git ignored).
--old-sim is optional: the root of the Oct-17 prototype (ruko_sim), for the side-by-side.
Real-data numbers (PaySim, Xente) come from real_baseline.json: summary stats only, no rows.
On Windows use `;` instead of `:` in PYTHONPATH.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, average_precision_score

OUT = Path(__file__).resolve().parent
QS = [0.1, 0.25, 0.5, 0.75, 0.9, 0.99]


def shape(amount, label):
    legit, fraud = amount[label == 0], amount[label == 1]
    med = legit.median()
    return {
        "legit_median": round(float(med), 2),
        "legit_q_over_median": {str(q): round(float(legit.quantile(q) / med), 3) for q in QS},
        "fraud_median_over_legit_median": round(float(fraud.median() / med), 2) if len(fraud) else None,
        "fraud_share_above_legit_p90": round(float((fraud > legit.quantile(0.9)).mean()), 3) if len(fraud) else None,
        "fraud_rate": round(float(label.mean()), 5),
        "n_rows": int(len(amount)),
        "n_fraud": int(label.sum()),
    }


def hours(h):
    p = np.bincount(h, minlength=24) / len(h)
    return [round(float(x), 4) for x in p]


def single_feature_auc(df, label, cols):
    out = {}
    for c in cols:
        x = df[c].astype(float).fillna(df[c].astype(float).median())
        if x.nunique() < 2:
            continue
        a = roc_auc_score(label, x)
        out[c] = {"roc_auc": round(float(max(a, 1 - a)), 4),
                  "pr_auc": round(float(average_precision_score(label, x if a >= 0.5 else -x)), 4)}
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["roc_auc"]))


def team(folder: Path):
    L = pd.read_parquet(folder / "ledger.parquet")
    U = pd.read_parquet(folder / "users.parquet")
    A = pd.read_parquet(folder / "accounts.parquet")
    J = pd.read_parquet(folder / "journeys.parquet")
    C = pd.read_parquet(folder / "context_events.parquet")
    days = (L.ts.max() - L.ts.min()).total_seconds() / 86400

    # Payments made by app users (the decision point RUKO actually scores).
    P = L[L.from_upi.isin(U.upi_id)].copy().sort_values("ts")
    P["label"] = P.label_is_scam.astype(int)
    P["hour"] = P.ts.dt.hour
    merch = set(A.loc[A.holder_type == "merchant", "upi_id"])
    P["to_merchant"] = P.to_upi.isin(merch).astype(int)
    created = A.set_index("upi_id").created_at
    P["payee_age_days"] = (P.ts - P.to_upi.map(created)).dt.total_seconds() / 86400
    P["log_amount"] = np.log1p(P.amount)
    # amount vs the payer's own running median (no look-ahead)
    P["amount_ratio_median"] = P.amount / P.groupby("from_upi").amount.transform(
        lambda s: s.expanding().median().shift(1))
    P["payee_new_to_user"] = (~P.duplicated(["from_upi", "to_upi"])).astype(int)
    P["typed"] = (P.entry_method == "typed").astype(int)
    P["payee_is_mule"] = P.to_upi.map(A.set_index("upi_id").is_mule).fillna(False).astype(int)

    per_user = P.groupby("from_upi").size() / days
    scam_users = J.user_id.nunique()
    leak = single_feature_auc(P, P.label, ["log_amount", "amount_ratio_median", "payee_age_days",
                                          "payee_new_to_user", "typed", "to_merchant", "hour",
                                          "payee_is_mule"])
    ctx = C.groupby(["event_type", "label_is_scam"]).size().unstack(fill_value=0)
    return {
        "rows": {k: int(len(v)) for k, v in dict(ledger=L, user_payments=P, users=U, accounts=A,
                                                 journeys=J, context_events=C).items()},
        "days": round(days, 1),
        "flows": L.flow.value_counts().to_dict(),
        "entry_method_share": P.entry_method.value_counts(normalize=True).round(3).to_dict(),
        "p2m_share_of_user_payments": round(float(P.to_merchant.mean()), 3),
        "user_payments_per_day": {"median": round(float(per_user.median()), 2),
                                  "p90": round(float(per_user.quantile(.9)), 2)},
        "journeys": int(len(J)), "demo_journeys": int(J.is_demo.sum()),
        "victim_rate": round(scam_users / len(U), 4),
        "playbooks": J.playbook.value_counts().to_dict(),
        "scam_payments_per_journey": round(float(J.n_payments.mean()), 2),
        "scam_total_paid_median": float(J.total_paid.median()),
        "mules": int(A.is_mule.sum()),
        "shape": shape(P.amount, P.label),
        "shape_p2p_only": shape(P.amount[P.to_merchant == 0], P.label[P.to_merchant == 0]),
        "hour_profile_legit": hours(P.hour[P.label == 0]),
        "hour_profile_scam": hours(P.hour[P.label == 1]),
        "single_feature_separability": leak,
        "context_events_by_label": {k: {str(c): int(v) for c, v in r.items()} for k, r in ctx.iterrows()},
        "sms_lure_on_non_scam": int(((C.event_type == "sms_lure") & ~C.label_is_scam.astype(bool)).sum()),
    }


def old_sim(root: Path):
    F = pd.read_csv(root / "data/sim/features.csv.gz", low_memory=False)
    J = pd.read_csv(root / "data/sim/journeys.csv")
    U = pd.read_csv(root / "data/sim/users.csv")
    F["amount"] = np.expm1(F.log_amount)  # log_amount is log1p in ruko_ml.features
    F["label"] = F.is_scam.astype(int)
    per_user = F.groupby("user_id").size() / 60
    leak = single_feature_auc(F, F.label, ["log_amount", "amount_ratio_median_90d", "payee_age_days",
                                          "payee_new_to_user", "typed_by_hand", "payee_is_merchant",
                                          "hour", "hesitation_s", "call_active", "lure_max_conf_72h"])
    return {
        "rows": {"payments": int(len(F)), "users": int(len(U)), "journeys": int(len(J))},
        "p2m_share_of_user_payments": round(float(F.payee_is_merchant.mean()), 3),
        "user_payments_per_day": {"median": round(float(per_user.median()), 2),
                                  "p90": round(float(per_user.quantile(.9)), 2)},
        "victim_rate": round(J.user_id.nunique() / len(U), 4),
        "hard_negative_payments": int(F.hard_negative.notna().sum()),
        "shape": shape(F.amount, F.label),
        "hour_profile_legit": hours(F.hour[F.label == 0].astype(int)),
        "single_feature_separability": leak,
    }


def real():
    prev = json.load(open(OUT / "real_baseline.json"))
    return {k: {"shape": prev[k]["shape"], "hour_profile_legit": prev[k]["hour_profile_legit"],
                "per_user_txns_median": prev[k]["per_user_txns_median"]}
            for k in ("paysim", "xente_real")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--team", type=Path, default=Path("data"))
    ap.add_argument("--old-sim", type=Path, default=None)
    args = ap.parse_args()
    res = {"team_sim": team(args.team), "real": real()}
    if args.old_sim:
        res["old_sim"] = old_sim(args.old_sim)
    # how far each sim's legit hour profile is from real (Xente is the only real one)
    x = np.array(res["real"]["xente_real"]["hour_profile_legit"])
    for k in ("team_sim", "old_sim"):
        if k not in res:
            continue
        h = np.array(res[k]["hour_profile_legit"])
        res[k]["hour_profile_l1_vs_xente"] = round(float(np.abs(h - x).sum()), 3)
    (OUT / "results.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
