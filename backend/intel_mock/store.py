"""In-memory view of the simulated world that every mock organisation reads from.

Nothing here answers a question by itself; each mock (NPCI, banks, DoT, I4C) decides what it is
allowed to see. The one rule enforced for everyone: no data from after the sim clock is visible.
"""
from __future__ import annotations

import json
import re
from bisect import bisect_right, insort
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import pandas as pd

Visibility = Literal["none", "partner", "dpip"]


def bank_code(bank: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", bank.lower()).strip("-")


@dataclass
class Flow:
    """One side of a payment as seen from an account."""
    ts: datetime
    counterparty: str
    amount: float

    def __lt__(self, other: "Flow") -> bool:
        return self.ts < other.ts


@dataclass
class Store:
    data_dir: Path
    handles: dict[str, dict] = field(default_factory=dict)
    accounts: dict[str, dict] = field(default_factory=dict)       # by upi_id
    by_mobile: dict[str, dict] = field(default_factory=dict)
    inflows: dict[str, list[Flow]] = field(default_factory=dict)  # by payee upi_id, sorted by ts
    outflows: dict[str, list[Flow]] = field(default_factory=dict)
    reports: list[dict] = field(default_factory=list)
    reports_by_id: dict[str, list[dict]] = field(default_factory=dict)  # by identifier
    data_end: datetime | None = None
    now: datetime | None = None
    visibility: Visibility = "partner"
    latency_ms: int = 0
    live_payments: int = 0

    @classmethod
    def load(cls, data_dir: str | Path) -> "Store":
        s = cls(Path(data_dir))
        s.reset()
        return s

    def reset(self) -> None:
        d = self.data_dir
        manifest = json.loads((d / "manifest.json").read_text())
        self.data_end = datetime.fromisoformat(manifest["config"]["end"])
        self.now = self.data_end
        self.visibility, self.latency_ms, self.live_payments = "partner", 0, 0

        self.handles = {r["handle"]: r for r in _records(pd.read_parquet(d / "handles.parquet"))}
        self.accounts, self.by_mobile = {}, {}
        for a in _records(pd.read_parquet(d / "accounts.parquet")):
            a["bank_code"] = bank_code(a["bank"])
            self.accounts[a["upi_id"]] = a
            self.by_mobile[a["mobile"]] = a

        self.inflows, self.outflows = {}, {}
        led = pd.read_parquet(d / "ledger.parquet", columns=["ts", "from_upi", "to_upi", "amount"])
        for ts, frm, to, amt in zip([t.to_pydatetime() for t in led.ts], led.from_upi, led.to_upi, led.amount):
            self.inflows.setdefault(to, []).append(Flow(ts, frm, float(amt)))
            self.outflows.setdefault(frm, []).append(Flow(ts, to, float(amt)))
        # The ledger is already sorted by ts, so each list is sorted too.

        self.reports = _records(pd.read_parquet(d / "reports.parquet"))
        self.reports_by_id = {}
        for r in self.reports:
            self.reports_by_id.setdefault(r["identifier"], []).append(r)

    # ---------- clock ----------

    def set_clock(self, when: datetime) -> None:
        self.now = when

    def advance(self, hours: float) -> None:
        self.now = self.now + timedelta(hours=hours)

    def last_batch(self, at: datetime | None = None) -> datetime:
        """Daily batch jobs (MuleHunter, FRI refresh) run at midnight sim time."""
        at = at or self.now
        return at.replace(hour=0, minute=0, second=0, microsecond=0)

    # ---------- reads (never past `until`) ----------

    def window(self, flows: list[Flow], since: datetime, until: datetime) -> list[Flow]:
        lo = bisect_right(flows, Flow(since, "", 0))
        hi = bisect_right(flows, Flow(until, "", 0))
        return flows[lo:hi]

    def payments_in(self, upi: str, since: datetime, until: datetime) -> list[Flow]:
        return self.window(self.inflows.get(upi, []), since, until)

    def payments_out(self, upi: str, since: datetime, until: datetime) -> list[Flow]:
        return self.window(self.outflows.get(upi, []), since, until)

    def account_at(self, upi: str, at: datetime) -> dict | None:
        a = self.accounts.get(upi)
        return a if a and a["created_at"] <= at else None

    def reports_listed(self, identifier: str, by: datetime) -> list[dict]:
        return [r for r in self.reports_by_id.get(identifier, []) if r["listed_at"] <= by]

    # ---------- writes (live demo) ----------

    def add_payment(self, ts: datetime, frm: str, to: str, amount: float) -> None:
        insort(self.inflows.setdefault(to, []), Flow(ts, frm, amount))
        insort(self.outflows.setdefault(frm, []), Flow(ts, to, amount))
        self.live_payments += 1


def _records(df: pd.DataFrame) -> list[dict]:
    out = []
    for r in df.to_dict("records"):
        out.append({k: (v.to_pydatetime() if isinstance(v, pd.Timestamp) else
                        None if v is None or (isinstance(v, float) and pd.isna(v)) else v)
                    for k, v in r.items()})
    return out
