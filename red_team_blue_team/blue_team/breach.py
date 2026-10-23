"""Step 1: where did the shield break? Turn complaints into cases and check what RUKO said at the time.

A complaint (1930 call or NCRP report) names the accounts a victim paid. A *case* is that complaint
joined to the complainant's own payments to those accounts, made before it was filed, with the tier
and playbook RUKO gave each payment at the time (the replayed engine features, scored by the active
scorer through backend/api/policy.py, as `model.evaluate` does).

- held:    a case payment was interrupted (T2+) and a playbook named the scam
- unnamed: interrupted, but no playbook named it (the user only got a generic warning)
- missed:  no case payment was interrupted (the scam went through: the shield broke)

Nothing here reads the simulator's ground truth: not `label_*`, `flow`, `playbook` or `journey_id`
of the payments. The complainant is the one fact taken from the complaint itself (sim_v2 stores it
as the report's journey owner); `evaluate.py` alone looks at the truth, for scoring.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from blue_team import config, playbook_db, tokens
from model.evaluate import raw_features, tiers

TRUTH_COLUMNS = ("label_is_scam", "label_stage", "flow", "playbook", "journey_id", "journey_pay_index",
                 "payee_is_mule", "payee_mule_kind", "payee_merchant_kind")


@dataclass
class Scored:
    """Every replayed payment with what RUKO said about it, ground truth removed."""
    rows: pd.DataFrame          # one row per payment: tx_id, ts (UTC), user_id, payee_upi, amount, weight, tier, named
    feats: list[dict]           # engine features + request fields (entry_method, payer_says), row-aligned
    scorer: str


def score(table: pd.DataFrame, scorer: str = "ml", pbs: list[playbook_db.Playbook] | None = None) -> Scored:
    df = table.reset_index(drop=True)
    feats = raw_features(df)
    for f, em, says in zip(feats, df["entry_method"], df["payer_says"]):
        f["entry_method"], f["payer_says"] = em, (None if pd.isna(says) else says)
    pbs = pbs if pbs is not None else playbook_db.load()
    named = [playbook_db.name_scam(f, pbs) for f in feats]
    if scorer == "ml":
        from model import predict
        model = predict.load()
        p, fam = model.score_frame(_encode(df))
        scores = [{"p_scam": float(p[i]), "family_scores": {k: float(v[i]) for k, v in fam.items()},
                   "playbook": named[i]} for i in range(len(df))]
        version = model.version
    else:
        from api import rule_scorer
        scores = [{**rule_scorer.score(f), "playbook": named[i]} for i, f in enumerate(feats)]
        version = rule_scorer.MODEL_VERSION
    rows = pd.DataFrame({
        "tx_id": df["tx_id"], "ts": pd.to_datetime(df["ts"], utc=True), "user_id": df["user_id"],
        "payee_upi": df["payee_upi"], "amount": df["amount"].astype(float),
        # The replay kept a sample of everyday payments; its weights stand for all of them.
        "weight": df["weight"].astype(float),
        "tier": tiers(df, feats, scores), "named": named,
        "p_scam": [s["p_scam"] for s in scores],
    })
    return Scored(rows, feats, version)


def _encode(df: pd.DataFrame) -> pd.DataFrame:
    from model.data import encode_frame
    return encode_frame(df)


def complaints(world: Path, as_of: pd.Timestamp | None = None) -> pd.DataFrame:
    """One row per complaint: report_id, complainant user, filed_at, source, the accounts it names."""
    cfg = config.load()["breach"]
    rep = pd.read_parquet(Path(world) / "reports.parquet")
    jr = pd.read_parquet(Path(world) / "journeys.parquet")[["journey_id", "user_id"]]
    rep = rep[rep["source"].astype(str).isin([str(s) for s in cfg["sources"]]) & rep["journey_id"].notna()
              & ~rep["is_false"].astype(bool)]
    rep = rep.assign(filed_at=pd.to_datetime(rep["filed_at"], utc=True))
    if as_of is not None:
        rep = rep[rep["filed_at"] <= as_of]
    rep = rep.merge(jr, on="journey_id", how="inner")
    upi = rep[rep["identifier_type"] == "upi_id"]
    return (upi.groupby("report_id")
            .agg(user_id=("user_id", "first"), filed_at=("filed_at", "first"), source=("source", "first"),
                 accounts=("identifier", lambda s: sorted(set(s))))
            .reset_index())


def cases(scored: Scored, comp: pd.DataFrame) -> pd.DataFrame:
    """Complaints joined to the complainant's payments; status held / unnamed / missed; token document."""
    cfg = config.load()["breach"]
    inter = set(cfg["interrupt_tiers"])
    rows = scored.rows
    by_user = {u: g for u, g in rows.groupby("user_id")}
    out = []
    for c in comp.itertuples(index=False):
        g = by_user.get(c.user_id)
        if g is None:
            continue
        g = g[g["payee_upi"].isin(c.accounts) & (g["ts"] <= c.filed_at)].sort_values("ts")
        if g.empty:
            continue
        idx = g.index.to_numpy()
        interrupted = bool(np.isin(g["tier"].to_numpy(), list(inter)).any())
        named = [n for n in g["named"] if isinstance(n, str)]
        status = "missed" if not interrupted else ("held" if named else "unnamed")
        doc = tokens.case_document([(ts.timestamp(), scored.feats[i]) for ts, i in zip(g["ts"], idx)])
        out.append({
            "case_id": c.report_id, "user_id": c.user_id, "filed_at": c.filed_at, "source": c.source,
            "status": status, "n_payments": len(g), "total_inr": float(g["amount"].sum()),
            "first_ts": g["ts"].iloc[0], "last_ts": g["ts"].iloc[-1],
            "max_tier": max(g["tier"], key=lambda t: int(t[1])), "named": sorted(set(named)),
            # most often named; ties by name, so the result never depends on set order (PYTHONHASHSEED)
            "named_main": min(set(named), key=lambda n: (-named.count(n), n)) if named else None,
            "payees": sorted(set(g["payee_upi"])), "rows": idx.tolist(), "document": doc,
        })
    return pd.DataFrame(out)


def presumed_legit(scored: Scored, comp: pd.DataFrame) -> np.ndarray:
    """Payments to accounts no complaint names. Unreported scams still hide in here, so false-alarm
    rates measured on it are pessimistic."""
    named = set().union(*comp["accounts"]) if len(comp) else set()
    return ~scored.rows["payee_upi"].isin(named).to_numpy()


def load_table(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)
