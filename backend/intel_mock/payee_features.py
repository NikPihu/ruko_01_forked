"""Payee-account features a bank can compute about its own accounts, as of a moment in time.

These are the indicators real mule detection uses: fan-in, repeat payers, pass-through, hold
time, account age. Everything is computed only from payments up to `at`.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from statistics import median

from .store import Store

# Stand-in for RBI's MuleHunter: a fixed logistic score over bank-visible features.
# Hand-set weights, so it is transparent; swap in a trained model later.
MULEHUNTER_MIN_AGE_DAYS = 7  # the batch only scores accounts with a week of history
MULEHUNTER_WEIGHTS = {"bias": -4.0, "pass_through": 2.5, "strangers": 2.0, "young": 1.0, "fan_in": 0.01}


def payee_features(s: Store, upi: str, at: datetime) -> dict | None:
    acct = s.account_at(upi, at)
    if acct is None:
        return None
    in_7d = s.payments_in(upi, at - timedelta(days=7), at)
    in_24h = [f for f in in_7d if f.ts > at - timedelta(hours=24)]
    in_6h = [f for f in in_24h if f.ts > at - timedelta(hours=6)]
    out_7d = s.payments_out(upi, at - timedelta(days=7), at)
    out_24h = [f for f in out_7d if f.ts > at - timedelta(hours=24)]
    in_30d = s.payments_in(upi, at - timedelta(days=30), at)

    # A repeat payer pays on two or more different days (split tranches in one sitting don't count).
    days_by_payer: dict[str, set] = {}
    for f in in_30d:
        days_by_payer.setdefault(f.counterparty, set()).add(f.ts.date())
    repeat = (sum(len(d) > 1 for d in days_by_payer.values()) / len(days_by_payer)) if days_by_payer else None

    inflow_24h, outflow_24h = sum(f.amount for f in in_24h), sum(f.amount for f in out_24h)
    inflow_7d, outflow_7d = sum(f.amount for f in in_7d), sum(f.amount for f in out_7d)
    regions = {s.accounts[f.counterparty]["region"] for f in in_7d if f.counterparty in s.accounts}

    return {
        "account_age_days": round((at - acct["created_at"]).total_seconds() / 86400, 1),
        "kyc_age_days": round((at - acct["kyc_at"]).total_seconds() / 86400, 1),
        "uniq_payers_6h": len({f.counterparty for f in in_6h}),
        "uniq_payers_24h": len({f.counterparty for f in in_24h}),
        "uniq_payers_7d": len({f.counterparty for f in in_7d}),
        "payer_regions_7d": len(regions),
        "repeat_payer_ratio_30d": None if repeat is None else round(repeat, 3),
        "inflow_24h": round(inflow_24h), "outflow_24h": round(outflow_24h),
        "pass_through_24h": round(min(outflow_24h / inflow_24h, 1.0), 3) if inflow_24h else None,
        "pass_through_7d": round(min(outflow_7d / inflow_7d, 1.0), 3) if inflow_7d else None,
        "median_hold_min": _median_hold(s, upi, out_7d, at),
    }


def _median_hold(s: Store, upi: str, outflows, at: datetime) -> float | None:
    """Minutes between each outgoing payment and the latest incoming payment before it."""
    holds = []
    for o in outflows:
        prior = s.payments_in(upi, o.ts - timedelta(days=2), o.ts)
        if prior:
            holds.append((o.ts - prior[-1].ts).total_seconds() / 60)
    return round(median(holds), 1) if holds else None


def mulehunter_score(s: Store, upi: str, cache: dict) -> tuple[float | None, datetime]:
    """Score as of the last daily batch. Fresh accounts are not scored until they have history."""
    batch = s.last_batch()
    key = (upi, batch)
    if key not in cache:
        cache[key] = _score_at(s, upi, batch)
    return cache[key], batch


def _score_at(s: Store, upi: str, batch: datetime) -> float | None:
    acct = s.account_at(upi, batch)
    if acct is None or (batch - acct["created_at"]).days < MULEHUNTER_MIN_AGE_DAYS:
        return None
    f = payee_features(s, upi, batch)
    if f["uniq_payers_7d"] == 0:
        return None
    w = MULEHUNTER_WEIGHTS
    strangers = (1 - (f["repeat_payer_ratio_30d"] or 0)) if f["uniq_payers_7d"] >= 5 else 0
    z = (w["bias"] + w["pass_through"] * (f["pass_through_7d"] or 0) + w["strangers"] * strangers
         + w["young"] * (f["account_age_days"] < 60) + w["fan_in"] * min(f["uniq_payers_7d"], 50))
    return round(1 / (1 + math.exp(-z)), 3)
