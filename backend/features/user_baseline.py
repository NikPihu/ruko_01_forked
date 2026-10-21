"""The payer's own history, as the payer's bank / payment app already has it.

Loaded once from the simulator's ledger. For a payment at time `at` it gives only what the bank
knew just before that moment: the largest and median payment in the 90 days before `at`, and every
payee the user paid before `at`. The payment being judged, and anything after it, never count as
the user's "usual" (otherwise a Rs 95,000 scam payment would make Rs 95,000 look normal, and the
mule would look like a payee the user already knows).
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

import pandas as pd

WINDOW = timedelta(days=90)


@dataclass
class UserBaseline:
    max_90d: float | None = None
    median_90d: float | None = None
    known_payees: set[str] = field(default_factory=set)


@dataclass
class _History:
    """One user's payments, oldest first."""
    ts: list[datetime] = field(default_factory=list)
    amount: list[float] = field(default_factory=list)
    payee: list[str] = field(default_factory=list)


class Baselines:
    def __init__(self) -> None:
        self.history: dict[str, _History] = {}
        self.user_upi: dict[str, str] = {}

    @classmethod
    def from_data(cls, data_dir: str | Path) -> "Baselines":
        d = Path(data_dir)
        b = cls()
        users = pd.read_parquet(d / "users.parquet", columns=["user_id", "upi_id"])
        b.user_upi = dict(zip(users.user_id, users.upi_id))
        led = pd.read_parquet(d / "ledger.parquet", columns=["ts", "from_upi", "to_upi", "amount"])
        upi_to_user = {v: k for k, v in b.user_upi.items()}
        led = led[led.from_upi.isin(upi_to_user)].sort_values("ts", kind="stable")
        for upi, g in led.groupby("from_upi", sort=False):
            b.history[upi_to_user[upi]] = _History(
                ts=[t.to_pydatetime() for t in g.ts], amount=g.amount.astype(float).tolist(),
                payee=g.to_upi.str.lower().tolist())
        return b

    def get(self, user_id: str, at: datetime | None = None) -> UserBaseline:
        """The user's history as of just before `at` (strictly earlier payments only).
        `at=None` means the whole loaded history (tests and offline summaries)."""
        h = self.history.get(user_id)
        if h is None:
            return UserBaseline()
        end = len(h.ts) if at is None else bisect_left(h.ts, at)
        start = 0 if at is None else bisect_left(h.ts, at - WINDOW)
        amounts = h.amount[start:end]
        return UserBaseline(max_90d=max(amounts) if amounts else None,
                            median_90d=median(amounts) if amounts else None,
                            known_payees=set(h.payee[:end]))
