"""A tiny synthetic workspace: one new scam (voice-clone 'relative' calls), one known scam, legit life."""
from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]
for p in ("backend", "ml", "data", "red_team_blue_team"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from features.build import FAMILY  # noqa: E402

from blue_team import cluster, playbook_db, tokens  # noqa: E402
from blue_team.breach import Scored  # noqa: E402
from blue_team.evidence import Workspace  # noqa: E402

T0 = datetime(2026, 10, 1, 10, tzinfo=timezone.utc)


def features(**kw) -> dict:
    f = dict.fromkeys(FAMILY)
    f.update(amount_inr=500.0, first_time_payee=False, entry_typed=False, payee_holder_type="merchant",
             payee_verified_merchant=True, payee_in_run=False, attempts_72h=0, episode_state=0, stage=0,
             entry_method="qr", payer_says=None)
    f.update(kw)
    return f


def relative_call(r: random.Random) -> dict:
    return features(on_call=True, voip_call=r.random() < 0.7, caller_unknown=None, entry_typed=True, entry_method="typed",
                    payer_says="family" if r.random() < 0.9 else None, amount_inr=r.uniform(15000, 60000),
                    first_time_payee=True, payee_holder_type="person", payee_verified_merchant=False,
                    session_hesitation=r.random() < 0.6)   # not dictated: else digital_arrest names it


def marketplace_qr(r: random.Random) -> dict:
    return features(entry_method="qr", amount_inr=r.uniform(100, 900), first_time_payee=True, payee_holder_type="person",
                    payee_verified_merchant=False, payee_pass_through_24h=1.0 if r.random() < 0.8 else 0.0,
                    attempts_72h=r.choice([2, 3]), session_abandoned_30m=1.0 if r.random() < 0.5 else 0.0)


def known_trading(r: random.Random) -> dict:
    return features(lure_tag="trading_tip", lure_max_conf_72h=0.8, entry_typed=True, entry_method="typed",
                    payer_says="investment", amount_inr=r.uniform(5000, 20000), first_time_payee=True,
                    payee_holder_type="person", payee_verified_merchant=False)


@pytest.fixture(scope="session")
def ws() -> Workspace:
    r = random.Random(0)
    pbs = playbook_db.load()
    feats, rows, cases = [], [], []

    def add(f, user, payee, ts, weight=4.0):
        feats.append(f)
        rows.append({"tx_id": f"tx{len(rows)}", "ts": ts, "user_id": user, "payee_upi": payee,
                     "amount": f["amount_inr"], "weight": weight, "tier": "T0",
                     "named": playbook_db.name_scam(f, pbs), "p_scam": 0.01})
        return len(rows) - 1

    for i in range(600):                                   # everyday life: kirana QR payments
        add(features(amount_inr=r.uniform(50, 900)), f"u{i % 200}", f"shop{i % 30}@okaxis", T0 + timedelta(minutes=i))
    for k, (make, n) in enumerate(((relative_call, 10), (known_trading, 6), (marketplace_qr, 10))):
        for j in range(n):
            user, payee = f"v{k}_{j}", f"mule{k}_{j % 3}@ybl"
            ts = T0 + timedelta(days=1 + j)
            idx = [add(make(r), user, payee, ts, weight=1.0), add(make(r), user, payee, ts + timedelta(minutes=40), weight=1.0)]
            named = [rows[i]["named"] for i in idx if rows[i]["named"]]
            cases.append({"case_id": f"rep{k}_{j}", "user_id": user, "filed_at": pd.Timestamp(ts + timedelta(days=3)),
                          "source": "1930", "status": "missed" if not named else "held", "n_payments": 2,
                          "total_inr": sum(rows[i]["amount"] for i in idx), "first_ts": pd.Timestamp(ts),
                          "last_ts": pd.Timestamp(ts + timedelta(minutes=40)), "max_tier": "T0" if not named else "T3",
                          "named": sorted(set(named)), "named_main": named[0] if named else None, "payees": [payee],
                          "rows": idx, "document": tokens.case_document([(rows[i]["ts"].timestamp(), feats[i]) for i in idx])})
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    scored = Scored(df, feats, "test")
    case_df = pd.DataFrame(cases)
    res = cluster.run(case_df)
    legit = ~df["payee_upi"].str.startswith("mule").to_numpy()
    return Workspace(scored, case_df, res, legit, pbs)


@pytest.fixture(scope="session")
def new_cluster(ws) -> str:
    """The cluster of the voice-clone 'relative' cases."""
    news = [c for c in ws.clusters.clusters if c.kind == "new" and all(i.startswith("rep0_") for i in c.case_ids)]
    assert news, [(c.cluster_id, c.kind, c.case_ids) for c in ws.clusters.clusters]
    return news[0].cluster_id


@pytest.fixture()
def tmp_db(tmp_path) -> Path:
    import shutil
    from blue_team import config
    shutil.copytree(config.PLAYBOOKS / "known", tmp_path / "playbooks" / "known")
    return tmp_path / "playbooks"


__all__ = ["features", "np"]
