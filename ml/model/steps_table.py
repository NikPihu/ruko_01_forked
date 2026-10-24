"""A replay table (dataset.replay) as scam steps: one column per step of contracts/steps.json, 1.0 seen,
0.0 measured and not seen, NaN unknown (rule 1). Both readings of the engine are merged, as on the
payment path (api/main.py): the server's (features/steps.py server_steps on the engine features and
the request) and the phone's (phone_steps on the dev_* device features, which its verdict carries).

Used by the playbook search evaluation (model.search_eval) and by lgbm-0.3 as step features.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pandas as pd

from features.steps import STEP_IDS, merge, phone_steps, server_steps

TAG = {"arrest_threat", "kyc", "task_job", "trading_tip", "refund", "other_scam"}


def _clean(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return v.item() if hasattr(v, "item") else v


def _request(row: dict) -> SimpleNamespace:
    """The parts of the request server_steps reads. The table keeps the top lure only (its tag and
    confidence), which is all the lure steps need; no SMS consent -> lures unknown."""
    lures = None
    if row.get("has_context") and row.get("consent_sms"):
        tag, conf = row.get("lure_tag"), row.get("lure_max_conf_72h")
        lures = [SimpleNamespace(tag=tag, conf=float(conf))] if tag in TAG and conf is not None else []
    ctx = SimpleNamespace(lures=lures) if lures is not None else None
    return SimpleNamespace(context=ctx, entry_method=row.get("entry_method"))


def row_steps(row: dict) -> dict[str, bool | None]:
    row = {k: _clean(v) for k, v in row.items()}
    dev = {k: v for k, v in row.items() if k.startswith("dev_")}
    phone = phone_steps(dev) if any(v is not None for v in dev.values()) else {}
    return merge(server_steps(row, _request(row)), phone)


def table_steps(df: pd.DataFrame) -> pd.DataFrame:
    """One row per payment, one column per step (the step id, e.g. `lure:kyc`)."""
    val = {True: 1.0, False: 0.0, None: np.nan}
    rows = [row_steps(r) for r in df.to_dict("records")]
    return pd.DataFrame([[val[r.get(s)] for s in STEP_IDS] for r in rows], columns=list(STEP_IDS), index=df.index)
