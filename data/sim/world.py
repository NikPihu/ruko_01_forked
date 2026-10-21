"""Shared mutable state for one simulation run, plus the helpers every generator uses."""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from .config import HANDLES, SimConfig
from .names import FIRST, FOREIGN_CODES, LAST


@dataclass
class World:
    cfg: SimConfig
    rng: random.Random
    # A second stream for later additions (sim/extras.py), so they never shift the core world.
    aux: random.Random = field(default_factory=lambda: random.Random(1))
    accounts: list[dict] = field(default_factory=list)
    users: list[dict] = field(default_factory=list)
    ledger: list[dict] = field(default_factory=list)
    context_events: list[dict] = field(default_factory=list)
    journeys: list[dict] = field(default_factory=list)
    reports: list[dict] = field(default_factory=list)

    # Lookups filled while building accounts.
    by_upi: dict[str, dict] = field(default_factory=dict)
    users_by_id: dict[str, dict] = field(default_factory=dict)
    kirana_by_region: dict[str, list[str]] = field(default_factory=dict)
    pharmacies: list[str] = field(default_factory=list)
    hospitals: list[str] = field(default_factory=list)
    billers: list[str] = field(default_factory=list)
    mules: list[dict] = field(default_factory=list)
    cash_out: list[dict] = field(default_factory=list)
    # People outside our app who also fall for scams and pay the same mules.
    external: list[dict] = field(default_factory=list)
    external_scam_rows: list[dict] = field(default_factory=list)
    scam_numbers: list[str] = field(default_factory=list)

    _used_mobiles: set[str] = field(default_factory=set)
    _used_upi: set[str] = field(default_factory=set)

    # ---------- identifiers ----------

    def new_mobile(self, country: str = "+91") -> str:
        while True:
            if country == "+91":
                n = f"+91{self.rng.choice('6789')}{self.rng.randrange(10**9):09d}"
            else:
                n = f"{country}{self.rng.randrange(10**9, 10**10)}"
            if n not in self._used_mobiles:
                self._used_mobiles.add(n)
                return n

    def new_upi(self, local: str, handle: str) -> str:
        base, n = local, 0
        while f"{local}@{handle}" in self._used_upi:
            n += 1
            local = f"{base}{n}"
        upi = f"{local}@{handle}"
        self._used_upi.add(upi)
        return upi

    def person_name(self) -> tuple[str, str]:
        return self.rng.choice(FIRST), self.rng.choice(LAST)

    def pick_handle(self):
        return self.rng.choice(HANDLES)

    def add_account(self, **kw) -> dict:
        # Account ids are assigned later in shuffled order so the id never hints at the label.
        acct = {"account_id": None, **kw}
        self.accounts.append(acct)
        self.by_upi[acct["upi_id"]] = acct
        return acct

    def foreign_or_local_number(self, p_foreign: float) -> str:
        if self.rng.random() < p_foreign:
            return self.new_mobile(self.rng.choice(FOREIGN_CODES))
        return self.new_mobile()

    # ---------- randomness ----------

    def lognormal_amount(self, median: float, sigma: float, lo: float, hi: float) -> int:
        v = self.rng.lognormvariate(math.log(median), sigma)
        return int(round(min(max(v, lo), hi)))

    def uniform_td(self, lo_min: float, hi_min: float) -> timedelta:
        return timedelta(minutes=self.rng.uniform(lo_min, hi_min))

    def day_time(self, day: datetime) -> datetime:
        # Payments cluster in the day; few at night.
        hour = self.rng.choices(range(24), weights=[
            1, 1, 1, 1, 1, 2, 4, 6, 8, 9, 9, 9, 9, 8, 8, 8, 9, 10, 11, 11, 10, 7, 4, 2])[0]
        return day.replace(hour=hour, minute=self.rng.randrange(60), second=self.rng.randrange(60))

    # ---------- records ----------

    def pay(self, ts: datetime, frm: str, to: str, amount: float, entry: str, flow: str,
            journey_id: Optional[str] = None, is_scam: bool = False,
            stage: Optional[str] = None) -> Optional[dict]:
        if ts > self.cfg.end:
            return None
        row = {"ts": ts, "from_upi": frm, "to_upi": to, "amount": float(amount),
               "entry_method": entry, "flow": flow, "journey_id": journey_id,
               "label_is_scam": is_scam, "label_stage": stage}
        self.ledger.append(row)
        return row

    def event(self, ts: datetime, user_id: str, event_type: str, attrs: dict,
              journey_id: Optional[str] = None, stage: Optional[str] = None) -> None:
        if ts > self.cfg.end:
            return
        self.context_events.append({
            "ts": ts, "user_id": user_id, "event_type": event_type,
            "attrs": json.dumps(attrs, sort_keys=True), "journey_id": journey_id,
            "label_is_scam": journey_id is not None, "label_stage": stage,
        })

    def call(self, ts: datetime, user_id: str, caller: str, minutes: float, in_contacts: bool,
             kind: str = "sim", direction: str = "incoming",
             journey_id: Optional[str] = None, stage: Optional[str] = None) -> datetime:
        """Log call_started / call_ended; returns the end time."""
        attrs = {"caller_number": caller, "call_kind": kind, "in_contacts": in_contacts,
                 "direction": direction, "country_code": caller[:-10]}
        if kind == "voip":
            attrs["voip_caller_is_number"] = True
        self.event(ts, user_id, "call_started", attrs, journey_id, stage)
        end = ts + timedelta(minutes=minutes)
        self.event(end, user_id, "call_ended", {**attrs, "duration_min": round(minutes, 1)},
                   journey_id, stage)
        return end
