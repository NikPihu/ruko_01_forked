"""Scorecard for reference datasets (and, later, for sim_v1): which one is worth learning from?

    PYTHONPATH=backend:ml:data python -m eval.datasets.score
    -> data/eval/datasets/scorecard.json

Five checks, each answering one question:
  schema     Does it have what RUKO needs (payer history, payee, P2P/P2M, INR, time of day)?
  npci       Do its amounts and P2P/P2M mix match the real NPCI numbers? (INR UPI sets only)
  behaviour  Does it look like real people over time (hour curve vs Xente, spread of activity)?
  labels     Are labels learnable but not trivial? (best single raw column, depth-2 tree)
  transfer   Train on it, test on the others (TSTR): does what it teaches carry over?

The same functions score any table in the common shape of references.py, so sim_v1 and the
current data/sim are scored the same way in notebook 02.
"""
from __future__ import annotations

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.tree import DecisionTreeClassifier

from eval.datasets.references import Ref, load_all, npci_bank_shares

OUT = Path(__file__).resolve().parent
ANCHORS = json.loads((OUT.parent / "realism" / "npci_anchors.json").read_text())["targets"]
HIST_FEATURES = ["rel_log_amount", "hour", "amount_vs_user", "user_prior_txns", "payee_new_to_user",
                 "payee_prior_inflows"]


# ---------- features shared by every dataset (currency free) ----------

def features(tx: pd.DataFrame) -> pd.DataFrame:
    """Per-payment features from the payment and the history before it (never after)."""
    f = pd.DataFrame(index=tx.index)
    legit_med = tx.amount[tx.label == 0].median()
    la = np.log1p(tx.amount.clip(lower=0))
    f["rel_log_amount"] = la - np.log1p(legit_med)
    f["hour"] = tx.ts.dt.hour
    if tx.user.notna().any():
        g = la.groupby(tx.user)
        n_prev = g.cumcount()
        mean_prev = (g.cumsum() - la) / n_prev.replace(0, np.nan)
        f["amount_vs_user"] = la - mean_prev
        f["user_prior_txns"] = n_prev
    else:
        f["amount_vs_user"] = np.nan
        f["user_prior_txns"] = np.nan
    if tx.user.notna().any() and tx.payee.notna().any():
        f["payee_new_to_user"] = (~tx.duplicated(["user", "payee"])).astype(float)
    else:
        f["payee_new_to_user"] = np.nan
    f["payee_prior_inflows"] = tx.groupby("payee").cumcount().astype(float) if tx.payee.notna().any() else np.nan
    return f


# ---------- 1. schema ----------

def schema(r: Ref) -> dict:
    t = r.tx
    checks = {
        "payer_history": bool(t.user.notna().any() and t.user.nunique() < 0.5 * len(t)),
        "payee_id": bool(t.payee.notna().any()),
        "p2p_p2m": bool(t.kind.isin(["P2P", "P2M"]).any()),
        "inr_upi": r.is_upi,
        "time_of_day": bool(t.ts.dt.hour.nunique() > 12),
    }
    return {"checks": checks, "score": sum(checks.values()) / len(checks)}


# ---------- 2. NPCI anchors ----------

def npci_fit(tx: pd.DataFrame, is_upi: bool) -> dict | None:
    if not is_upi:
        return None
    p2p, p2m = tx[tx.kind == "P2P"], tx[tx.kind == "P2M"]
    got = {}
    if len(p2p) and len(p2m):
        got["p2m_share_of_volume"] = len(p2m) / (len(p2p) + len(p2m))
        got["p2m_share_of_value"] = p2m.amount.sum() / (p2p.amount.sum() + p2m.amount.sum())
        got["avg_ticket_p2p_inr"] = p2p.amount.mean()
        got["avg_ticket_p2m_inr"] = p2m.amount.mean()
        got["p2p_share_below_500"] = (p2p.amount < 500).mean()
        got["p2m_share_below_500"] = (p2m.amount < 500).mean()
    rows = {}
    for k, v in got.items():
        a = ANCHORS[k]
        err = abs(v - a["value"]) / a["value"] if "tolerance_rel" in a else abs(v - a["value"])
        tol = a.get("tolerance_rel", a.get("tolerance"))
        rows[k] = {"got": round(float(v), 3), "target": a["value"], "pass": bool(err <= tol),
                   "error": round(float(err), 3)}
    bank_l1 = None
    if tx.bank.notna().any():
        npci = npci_bank_shares()
        mine = tx.bank.value_counts(normalize=True)
        common = [b for b in mine.index if b in npci.index and b != "Other"]
        if common:
            a, b = npci[common] / npci[common].sum(), mine[common] / mine[common].sum()
            bank_l1 = round(float((a - b).abs().sum()), 3)
    n = len(rows)
    score = (sum(r["pass"] for r in rows.values()) / n) if n else 0.0
    return {"anchors": rows, "bank_mix_l1_vs_npci": bank_l1, "score": score}


# ---------- 3. behaviour ----------

def hour_profile(ts: pd.Series) -> np.ndarray:
    return np.bincount(ts.dt.hour, minlength=24) / len(ts)


def behaviour(tx: pd.DataFrame, xente_hours: np.ndarray) -> dict:
    legit = tx[tx.label == 0]
    l1 = float(np.abs(hour_profile(legit.ts) - xente_hours).sum())
    out = {"hour_l1_vs_xente": round(l1, 3),
           "night_share_1to5": round(float(legit.ts.dt.hour.between(1, 5).mean()), 4)}
    if tx.user.notna().any() and tx.user.nunique() < 0.5 * len(tx):
        per_user = legit.groupby("user").size()
        out["payments_per_user_cv"] = round(float(per_user.std() / per_user.mean()), 3)
        out["payments_per_user_p50_p90"] = [float(per_user.median()), float(per_user.quantile(.9))]
    # 0.0 = same as real Xente, 1.0 = no overlap; scored so 1 is best
    out["score"] = max(0.0, 1 - l1)
    return out


# ---------- 4. labels: learnable but not trivial ----------

def _encode(raw: pd.DataFrame) -> pd.DataFrame:
    X = pd.DataFrame(index=raw.index)
    for c in raw.columns:
        s = raw[c]
        if pd.api.types.is_numeric_dtype(s) or pd.api.types.is_bool_dtype(s):
            X[c] = s.astype(float)
        elif s.nunique() <= 200:
            X[c] = s.astype("category").cat.codes.astype(float)
    return X


def label_quality(raw: pd.DataFrame, y: np.ndarray, max_rows: int = 400_000, seed: int = 7) -> dict:
    """Best single column and a depth-2 tree, with out-of-fold predictions so nothing is memorised."""
    if len(y) > max_rows:  # keep every positive, sample negatives
        rng = np.random.default_rng(seed)
        pos = np.flatnonzero(y == 1)
        neg = rng.choice(np.flatnonzero(y == 0), max_rows - len(pos), replace=False)
        idx = np.sort(np.concatenate([pos, neg]))
        raw, y = raw.iloc[idx], y[idx]
    X = _encode(raw.reset_index(drop=True)).fillna(-1)
    cv = StratifiedKFold(5, shuffle=True, random_state=seed)
    single = {}
    for c in X.columns:
        p = cross_val_predict(DecisionTreeClassifier(max_depth=3, min_samples_leaf=50), X[[c]], y,
                              cv=cv, method="predict_proba")[:, 1]
        single[c] = round(float(roc_auc_score(y, p)), 4)
    single = dict(sorted(single.items(), key=lambda kv: -kv[1]))
    p = cross_val_predict(DecisionTreeClassifier(max_depth=2, min_samples_leaf=50), X, y, cv=cv,
                          method="predict_proba")[:, 1]
    tree_auc = float(roc_auc_score(y, p))
    best = max(single.values()) if single else 0.5
    # Sweet spot: some signal (> 0.6) but no single column that gives it away (< 0.95).
    if tree_auc < 0.6:
        verdict, score = "no learnable signal (labels look random)", 0.2
    elif best >= 0.95 or tree_auc >= 0.98:
        verdict, score = "too easy (a simple rule gives the label away)", 0.3
    else:
        verdict, score = "learnable, not trivial", 1.0
    return {"best_single_column": single, "depth2_tree_auc": round(tree_auc, 4), "verdict": verdict,
            "score": score}


# ---------- 5. transfer (TSTR) ----------

def _time_split(f: pd.DataFrame, y: np.ndarray, frac: float = 0.7):
    k = int(len(y) * frac)
    return (f.iloc[:k], y[:k]), (f.iloc[k:], y[k:])


def transfer(feats: dict[str, tuple[pd.DataFrame, np.ndarray]], seed: int = 7) -> pd.DataFrame:
    """PR-AUC lift (PR-AUC / positive rate) for model trained on row dataset, tested on column dataset."""
    models = {}
    for n, (f, y) in feats.items():
        (Xtr, ytr), _ = _time_split(f, y)
        if ytr.sum() < 10:
            continue
        m = lgb.LGBMClassifier(n_estimators=200, learning_rate=0.05, num_leaves=31, min_child_samples=50,
                               subsample=0.8, subsample_freq=1, colsample_bytree=0.8, random_state=seed,
                               verbose=-1)
        m.fit(Xtr[HIST_FEATURES], ytr)
        models[n] = m
    rows = {}
    for tr, m in models.items():
        rows[tr] = {}
        for te, (f, y) in feats.items():
            _, (Xte, yte) = _time_split(f, y)
            if yte.sum() < 5:
                rows[tr][te] = np.nan
                continue
            p = m.predict_proba(Xte[HIST_FEATURES])[:, 1]
            rows[tr][te] = round(float(average_precision_score(yte, p) / yte.mean()), 2)
    return pd.DataFrame(rows).T  # rows = trained on, columns = tested on


# ---------- put together ----------

WEIGHTS = {"schema": 0.25, "npci": 0.25, "behaviour": 0.15, "labels": 0.2, "transfer": 0.15}


def scorecard(refs: dict[str, Ref]) -> dict:
    xh = hour_profile(refs["xente_real"].tx.query("label == 0").ts)
    feats = {n: (features(r.tx), r.tx.label.to_numpy()) for n, r in refs.items()}
    tstr = transfer(feats)
    # transfer score: median lift this dataset's model reaches on the other datasets, capped at 10x
    out = {}
    for n, r in refs.items():
        others = tstr.loc[n].drop(n).dropna() if n in tstr.index else pd.Series(dtype=float)
        t_score = float(np.clip(others.median() / 10, 0, 1)) if len(others) else 0.0
        s = {"meta": {"rows": len(r.tx), "positives": int(r.tx.label.sum()), "positive_rate": float(r.tx.label.mean()),
                      "currency": r.currency, "label": r.label_kind, "real": r.real, "notes": r.notes},
             "schema": schema(r), "npci": npci_fit(r.tx, r.is_upi), "behaviour": behaviour(r.tx, xh),
             "labels": label_quality(r.raw, r.tx.label.to_numpy()),
             "transfer": {"lift_on_others": others.to_dict(), "score": t_score}}
        parts = {k: (s[k]["score"] if s[k] else 0.0) for k in WEIGHTS}
        s["total"] = round(sum(WEIGHTS[k] * v for k, v in parts.items()), 3)
        s["parts"] = {k: round(v, 3) for k, v in parts.items()}
        out[n] = s
    return {"datasets": out, "transfer_matrix": tstr.to_dict(), "weights": WEIGHTS}


def mule_stats(r: Ref) -> dict:
    """How accounts that receive laundering money behave: fan-in, pass-through, forwarding delay."""
    t = r.tx
    acc = set(t.payee[t.label == 1])
    inn = t[t.payee.isin(acc)].groupby("payee").agg(senders=("user", "nunique"), in_amt=("amount", "sum"),
                                                     first_in=("ts", "min"))
    out = t[t.user.isin(acc)].groupby("user").agg(out_amt=("amount", "sum"), first_out=("ts", "min"))
    m = inn.join(out, how="inner")
    fwd = (m.first_out - m.first_in).dt.total_seconds() / 3600
    normal = t[(t.label == 0) & ~t.payee.isin(acc)].groupby("payee").user.nunique()
    return {"mule_senders_p50": float(inn.senders.median()), "mule_senders_p90": float(inn.senders.quantile(.9)),
            "normal_senders_p50": float(normal.median()), "normal_senders_p90": float(normal.quantile(.9)),
            "pass_through_p50": round(float((m.out_amt / m.in_amt).median()), 3),
            "forward_hours_p50_when_after": round(float(fwd[fwd >= 0].median()), 2)}


def behaviour_targets(refs: dict[str, Ref]) -> dict:
    """Numbers sim_v1 copies from real (Xente) behaviour and from the AML typology sets."""
    x = refs["xente_real"].tx.query("label == 0")
    per_user = x.groupby("user").size()
    days = (x.ts.max() - x.ts.min()).days
    rate = np.log(per_user / days)
    return {
        "_about": "Targets for sim_v1, from data/eval/datasets/score.py behaviour_targets(). Xente is real "
                  "(Uganda); only its shape is used: hour curve, weekday curve and how unequal users are.",
        "hour_profile": [round(float(v), 5) for v in hour_profile(x.ts)],
        "weekday_profile": [round(float(v), 5) for v in np.bincount(x.ts.dt.weekday, minlength=7) / len(x)],
        "payments_per_user_cv": round(float(per_user.std() / per_user.mean()), 3),
        "log_daily_rate_sigma": round(float(rate.std()), 3),
        "night_share_1to5": round(float(x.ts.dt.hour.between(1, 5).mean()), 4),
        "mules": {n: mule_stats(refs[n]) for n in ("saml_d", "ibm_amlworld_hi_small") if n in refs},
    }


def main():
    refs = load_all()
    res = scorecard(refs)
    (OUT / "scorecard.json").write_text(json.dumps(res, indent=1, default=float))
    targets = behaviour_targets(refs)
    (OUT.parent / "realism" / "behaviour_targets.json").write_text(json.dumps(targets, indent=1))
    rank = sorted(res["datasets"].items(), key=lambda kv: -kv[1]["total"])
    for n, s in rank:
        print(f"{s['total']:.3f}  {n:24s} {s['parts']}")


if __name__ == "__main__":
    main()
