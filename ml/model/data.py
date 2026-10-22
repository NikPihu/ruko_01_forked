"""Turning training rows (dataset/replay.py) into model inputs.

Server features are exactly the dict `features.build.build_features()` returns, so a trained model
can score a live request with no translation layer. Booleans become 0/1 and `None` becomes NaN
(LightGBM's "missing", which is never the same as 0 or false).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from dataset import device_features
from features.build import FAMILY

LURE_TAGS = ("arrest_threat", "kyc", "task_job", "trading_tip", "refund")

# Server features by family (C, L, P, B), from the engine's own feature map. Stage (S) is journey
# context: it feeds the combiner, never a family on its own.
SERVER_FAMILIES: dict[str, list[str]] = {}
for _name, _fam in FAMILY.items():
    if _name in ("lure_tag", "payee_holder_type"):
        continue  # encoded below
    SERVER_FAMILIES.setdefault(_fam, []).append(_name)
SERVER_FAMILIES["L"] += [f"lure_is_{t}" for t in LURE_TAGS]
SERVER_FAMILIES["P"] += ["payee_is_person"]
STAGE_FEATURES = SERVER_FAMILIES.pop("S")
DEVICE_FAMILIES = device_features.FAMILIES

# Checks that only run in certain situations: "who are you paying?" is asked only for typed payments
# of Rs 2,000 or more, and the caller is looked up only during an incoming SIM call from a stranger.
# Whether they ran says something about OTHER families (amount, entry, call), so a family model would
# learn "not asked = safe" from the gaps. Only a positive finding counts, as in the rules engine
# (`if f["story_mismatch"]`): unknown and "no finding" are both 0, never a reason to relax.
POSITIVE_ONLY = {"story_mismatch", "caller_registry_listed", "caller_fri_level"}

# What a bank's per-transaction fraud system sees today, for the ablation (deck slide 7).
TXN_ONLY = ["amount_inr", "amount_to_max_90d", "amount_to_median_90d", "first_time_payee", "entry_typed",
            "hour_ist", "payee_is_person", "payee_verified_merchant"]
# ... plus the lists it can already query (FRI, I4C Suspect Registry): today's stack.
TODAY = TXN_ONLY + ["payee_registry_listed", "payee_fri_level", "caller_registry_listed", "caller_fri_level"]


def _num(v) -> float:
    if v is None:
        return math.nan
    if isinstance(v, (bool, np.bool_)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return math.nan


def encode_features(f: dict, ts_hour: float | None = None) -> dict[str, float]:
    """One feature dict (from build_features, plus optional dev_ keys) -> numeric dict."""
    out = {k: _num(v) for k, v in f.items() if k not in ("lure_tag", "payee_holder_type")}
    for k in POSITIVE_ONLY & out.keys():
        out[k] = 0.0 if math.isnan(out[k]) else out[k]
    tag = f.get("lure_tag")
    for t in LURE_TAGS:
        out[f"lure_is_{t}"] = 1.0 if tag == t else 0.0
    ht = f.get("payee_holder_type")
    out["payee_is_person"] = math.nan if ht is None else float(ht == "person")
    if ts_hour is not None:
        out["hour_ist"] = float(ts_hour)
    return out


def encode_frame(df: pd.DataFrame) -> pd.DataFrame:
    """The training table -> a float frame with every server and device feature column."""
    cols: dict[str, pd.Series | np.ndarray] = {}
    for col in df.columns:
        if col in ("lure_tag", "payee_holder_type"):
            continue
        s = df[col]
        if s.dtype == bool or s.dtype == object or str(s.dtype) in ("boolean", "str", "string"):
            cols[col] = s.map(_num).astype("float64")
        elif pd.api.types.is_numeric_dtype(s):
            cols[col] = s.astype("float64")
        if col in POSITIVE_ONLY and col in cols:
            cols[col] = cols[col].fillna(0.0)
    for t in LURE_TAGS:
        cols[f"lure_is_{t}"] = (df["lure_tag"] == t).astype("float64")
    ht = df["payee_holder_type"]
    cols["payee_is_person"] = np.where(ht.isna(), np.nan, (ht == "person").astype("float64"))
    cols["hour_ist"] = df["ts"].dt.tz_convert("Asia/Kolkata").dt.hour.astype("float64")
    # World checks only, never model inputs: patterns that should NOT predict scams in a realistic world.
    cols["audit_round_100"] = (df["amount"] % 100 == 0).astype("float64")
    cols["audit_payer_asked"] = df["payer_says"].notna().astype("float64")
    return pd.DataFrame(cols, index=df.index)


def server_features() -> list[str]:
    return [f for fam in ("C", "L", "P", "B") for f in SERVER_FAMILIES[fam]] + STAGE_FEATURES + ["hour_ist"]


def device_feature_list() -> list[str]:
    return list(device_features.ALL)
