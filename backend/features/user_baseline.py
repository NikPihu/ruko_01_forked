"""The payer's own history, as the payer's bank / payment app already has it.

Loaded once from the simulator's ledger: largest and median payment in 90 days, and the set of
payees the user has paid before.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

import pandas as pd


@dataclass
class UserBaseline:
    max_90d: float | None = None
    median_90d: float | None = None
    known_payees: set[str] = field(default_factory=set)


class Baselines:
    def __init__(self) -> None:
        self.by_user: dict[str, UserBaseline] = {}
        self.user_upi: dict[str, str] = {}

    @classmethod
    def from_data(cls, data_dir: str | Path) -> "Baselines":
        d = Path(data_dir)
        b = cls()
        users = pd.read_parquet(d / "users.parquet", columns=["user_id", "upi_id"])
        b.user_upi = dict(zip(users.user_id, users.upi_id))
        led = pd.read_parquet(d / "ledger.parquet", columns=["from_upi", "to_upi", "amount"])
        upi_to_user = {v: k for k, v in b.user_upi.items()}
        led = led[led.from_upi.isin(upi_to_user)]
        for upi, g in led.groupby("from_upi"):
            amounts = g.amount.tolist()
            b.by_user[upi_to_user[upi]] = UserBaseline(
                max_90d=max(amounts), median_90d=median(amounts), known_payees=set(g.to_upi))
        return b

    def get(self, user_id: str) -> UserBaseline:
        return self.by_user.setdefault(user_id, UserBaseline())
