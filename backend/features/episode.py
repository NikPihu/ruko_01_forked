"""Task-scam episode: the same state machine as the phone's `EpisodeTracker.kt`.

    NONE --bait credit--> WATCHING --2+ outs to new payees and 2+ escalation steps--> ACTIVE
    WATCHING / ACTIVE --30 days with no bait and no out--> NONE
    WATCHING / ACTIVE --user: "I know them / real job"--> DISMISSED
    DISMISSED --a NEW bait sender--> WATCHING (fresh episode); --30 days--> NONE

Thresholds come from contracts/episode_rules.json; contracts/examples/episode_vectors.json holds the
cases both sides must agree on. The online engine trusts the phone's summary; this module rebuilds
episodes offline (from the ledger) and runs the shared vectors.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from features.bank_sms import Txn

RULES_PATH = Path(__file__).resolve().parents[2] / "contracts" / "episode_rules.json"
DAY_S = 86_400.0


def load_rules(path: Path = RULES_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class Episode:
    state: str = "none"                 # none | watching | active | dismissed
    start_ts: Optional[float] = None    # first bait credit
    last_activity_ts: Optional[float] = None
    dismissed_ts: Optional[float] = None
    bait: list[Txn] = field(default_factory=list)
    outs: list[Txn] = field(default_factory=list)
    known_senders: set[str] = field(default_factory=set)   # bait senders when dismissed
    paid_before: set[str] = field(default_factory=set)     # payees paid before the episode started


class EpisodeTracker:
    """Feed transactions in time order with `add`; read the summary with `summary(now)`."""

    def __init__(self, rules: Optional[dict] = None, sms_read: bool = True):
        self.r = rules or load_rules()
        self.sms_read = sms_read
        self.ep = Episode()
        self.history: list[Txn] = []    # every counted transaction, kept history_days

    # ---------- input ----------

    def add(self, t: Txn) -> None:
        if t.from_sms and not self.sms_read:
            return
        self._expire(t.ts)
        if self._duplicate(t):
            return
        self.history.append(t)
        if t.flow == "in":
            if self._is_bait(t):
                self._on_bait(t)
        else:
            self._on_out(t)

    def add_all(self, txns: Iterable[Txn]) -> "EpisodeTracker":
        for t in sorted(txns, key=lambda x: x.ts):
            self.add(t)
        return self

    def dismiss(self, ts: float) -> None:
        self._expire(ts)
        if self.ep.state in ("watching", "active"):
            self.ep = Episode(state="dismissed", dismissed_ts=ts,
                              known_senders={b.counterparty for b in self.ep.bait if b.counterparty})

    # ---------- rules ----------

    def _paid(self, before_ts: float) -> set[str]:
        return {h.counterparty for h in self.history if h.flow == "out" and h.counterparty and h.ts < before_ts}

    def _is_bait(self, t: Txn) -> bool:
        return t.amount <= self.r["bait_max_inr"] and (t.counterparty is None or t.counterparty not in self._paid(t.ts))

    def _on_bait(self, t: Txn) -> None:
        ep = self.ep
        if ep.state == "dismissed":
            if t.counterparty is None or t.counterparty in ep.known_senders:
                return
            ep = self.ep = Episode()
        if ep.state == "none":
            self.ep = ep = Episode(state="watching", start_ts=t.ts, paid_before=self._paid(t.ts))
        ep.bait.append(t)
        ep.last_activity_ts = t.ts

    def _on_out(self, t: Txn) -> None:
        ep = self.ep
        if ep.state not in ("watching", "active"):
            return
        ep.outs.append(t)
        ep.last_activity_ts = t.ts
        if (ep.state == "watching" and self._new_payee_outs(ep) >= self.r["active_min_outs"]
                and escalation_steps([o.amount for o in ep.outs], self.r["escalation_factor"])
                >= self.r["active_min_escalation_steps"]):
            ep.state = "active"

    def _new_payee_outs(self, ep: Episode) -> int:
        # An out with no named payee (some bank alerts) counts as a new payee: unknown is not safe.
        return sum(1 for o in ep.outs if o.counterparty is None or o.counterparty not in ep.paid_before)

    def _duplicate(self, t: Txn) -> bool:
        """A payment made in this app also arrives as a debit SMS; count it once."""
        win = self.r["same_payment_minutes"] * 60
        return any(h.flow == t.flow and h.amount == t.amount and abs(h.ts - t.ts) <= win
                   and h.from_sms != t.from_sms for h in self.history)

    def _expire(self, now: float) -> None:
        self.history = [h for h in self.history if now - h.ts <= self.r["history_days"] * DAY_S]
        ep, quiet = self.ep, self.r["quiet_close_days"] * DAY_S
        if ep.state in ("watching", "active") and now - ep.last_activity_ts >= quiet:
            self.ep = Episode()
        elif ep.state == "dismissed" and now - ep.dismissed_ts >= quiet:
            self.ep = Episode()

    # ---------- output ----------

    def summary(self, now: float, payee: Optional[str] = None) -> dict:
        """The `context.episode` object (c2-0.3). Null means unknown, never zero."""
        self._expire(now)
        ep, sms = self.ep, self.sms_read
        live = ep.state in ("watching", "active")
        outs = ep.outs if live else []
        bait_inr = sum(b.amount for b in ep.bait) if live else 0.0
        outs_inr = sum(o.amount for o in outs)
        named = {o.counterparty for o in outs if o.counterparty}
        return {
            "state": ep.state,
            "age_days": round((now - ep.start_ts) / DAY_S, 3) if live else None,
            "bait_credits": (len(ep.bait) if live else 0) if sms else None,
            "bait_inr": bait_inr if sms else None,
            "outs": len(outs),
            "outs_inr": outs_inr,
            "new_payees": len(named - ep.paid_before) + sum(1 for o in outs if o.counterparty is None),
            "escalation_steps": escalation_steps([o.amount for o in outs], self.r["escalation_factor"]),
            "last_out_inr": outs[-1].amount if outs else None,
            "out_to_in_ratio": round(outs_inr / bait_inr, 2) if sms and bait_inr else None,
            "payee_seen_in_episode": (payee.strip().lower() in named) if payee and live else None,
            "rules_version": self.r["version"],
        }


def escalation_steps(amounts: list[float], factor: float = 1.5) -> int:
    """How many payments in a row, ending with the latest, were each >= factor x the one before."""
    steps = 0
    for i in range(len(amounts) - 1, 0, -1):
        if amounts[i] >= factor * amounts[i - 1]:
            steps += 1
        else:
            break
    return steps
