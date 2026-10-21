"""Payment graph: who pays whom, built only from what RUKO could really see (task-scam-watcher.md §9).

Sources (never the simulator's full ledger or its labels):
    /v1/decide      user -> payee, every payment check
    /v1/episode     bait sender -> user, user -> payee (other apps too, through bank SMS)
    payee's bank    payee -> where it forwards money (only when that bank shares)
RUKO users are pseudonymised; other accounts stay plain because they must be looked up.
In memory for the demo; a Postgres `edges` table later. Edges older than 30 days are dropped unless
they are a case's evidence.

Signals it gives, all payee-family evidence (never enough for T2 on their own):
    crowd       many RUKO users got "rewards" from one account, or paid the same new payee
    money_loop  the payee forwards to the same place the bait sender does, or back to the bait sender
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, Optional

from evidence.store import pseudonym

KEEP = timedelta(days=30)
CROWD_BAIT_USERS = 5        # distinct users with a bait credit from one account in 7 days
CROWD_EPISODE_USERS = 3     # distinct users' episodes in which one account was a payee
CROWD_FANIN_6H = 10         # distinct RUKO users paying one account in 6 hours
MAX_EVENTS_PER_USER_DAY = 20
NEW_USER_WEIGHT = 0.5       # crowd votes from users first seen in the last 24 h count for less


@dataclass
class Edge:
    n: int = 0
    inr: float = 0.0
    first_ts: Optional[datetime] = None
    last_ts: Optional[datetime] = None
    sources: set[str] = field(default_factory=set)
    protected: bool = False     # part of a case's evidence
    hold_min: Optional[float] = None   # bank flows: median minutes the money stayed before moving on

    def add(self, inr: float, ts: datetime, source: str) -> None:
        self.n += 1
        self.inr += inr
        self.first_ts = min(self.first_ts or ts, ts)
        self.last_ts = max(self.last_ts or ts, ts)
        self.sources.add(source)


def user_node(user_id: str) -> str:
    return "u:" + pseudonym(user_id)[:16]


class GraphStore:
    def __init__(self) -> None:
        self.edges: dict[tuple[str, str], Edge] = {}
        self.out: dict[str, set[str]] = defaultdict(set)
        self.inn: dict[str, set[str]] = defaultdict(set)
        self.marks: dict[str, dict] = defaultdict(dict)        # node -> {"listed": True, "mulehunter": 0.8, ...}
        self.bait: dict[str, dict[str, datetime]] = defaultdict(dict)       # sender -> {user node: last ts}
        self.episode_payee: dict[str, dict[str, datetime]] = defaultdict(dict)  # payee -> {user node: ts}
        self.first_seen: dict[str, datetime] = {}
        self.flows_seen: dict[str, Optional[bool]] = {}         # account -> bank flows visible?
        self._events_today: dict[tuple[str, str], int] = defaultdict(int)

    def reset(self) -> None:
        self.__init__()

    # ---------- writes ----------

    def _edge(self, a: str, b: str, inr: float, ts: datetime, source: str) -> None:
        e = self.edges.setdefault((a, b), Edge())
        e.add(inr, ts, source)
        self.out[a].add(b)
        self.inn[b].add(a)

    def _seen(self, node: str, ts: datetime) -> None:
        self.first_seen[node] = min(self.first_seen.get(node, ts), ts)

    def add_payment(self, user_id: str, payee: str, inr: float, ts: datetime) -> None:
        u = user_node(user_id)
        self._seen(u, ts)
        self._edge(u, payee.strip().lower(), inr, ts, "decide")

    def add_episode(self, ev, now: datetime) -> bool:
        """Edges from an episode event. False when the device sent more than its daily cap."""
        u = user_node(ev.user_id)
        key = (u, now.date().isoformat())
        self._events_today[key] += 1
        if self._events_today[key] > MAX_EVENTS_PER_USER_DAY:
            return False
        self._seen(u, now)
        for a in ev.accounts:
            upi = a.upi_id.strip().lower()
            seen_at = now - timedelta(minutes=a.first_seen_min_ago)
            if a.role == "bait_sender":
                self._edge(upi, u, a.inr, seen_at, "episode")
                self.bait[upi][u] = now
            else:
                self._edge(u, upi, a.inr, seen_at, "episode")
                self.episode_payee[upi][u] = now
        return True

    def add_bank_flows(self, account: str, flows: Optional[dict]) -> None:
        """The payee's bank's answer: where this account forwards money. None means not visible."""
        account = account.strip().lower()
        if flows is None:
            self.flows_seen.setdefault(account, None)
            return
        self.flows_seen[account] = True
        as_of = datetime.fromisoformat(flows["as_of"])
        for o in flows.get("outbound", []):
            to = o["upi_id"].strip().lower()
            e = self.edges.setdefault((account, to), Edge())
            if "bank_flows" not in e.sources:  # a fresh snapshot, not a new payment
                e.n, e.inr = o["n"], o["inr"]
            e.hold_min = o.get("median_hold_min")
            e.first_ts, e.last_ts = e.first_ts or as_of, as_of
            e.sources.add("bank_flows")
            self.out[account].add(to)
            self.inn[to].add(account)

    def mark(self, account: str, **marks) -> None:
        self.marks[account.strip().lower()].update({k: v for k, v in marks.items() if v is not None})

    def protect(self, nodes: Iterable[str]) -> None:
        nodes = set(nodes)
        for (a, b), e in self.edges.items():
            if a in nodes and b in nodes:
                e.protected = True

    def expire(self, now: datetime) -> None:
        for k in [k for k, e in self.edges.items() if not e.protected and e.last_ts and now - e.last_ts > KEEP]:
            a, b = k
            del self.edges[k]
            self.out[a].discard(b)
            self.inn[b].discard(a)

    # ---------- signals ----------

    def _weight(self, users: dict[str, datetime], now: datetime, window: timedelta) -> float:
        w = 0.0
        for u, ts in users.items():
            if now - ts <= window:
                new = now - self.first_seen.get(u, now) < timedelta(hours=24)
                w += NEW_USER_WEIGHT if new else 1.0
        return w

    def account_signals(self, account: str, now: datetime) -> dict:
        """Crowd and money-loop features for one account (payee family only)."""
        acc = account.strip().lower()
        fanout = self._weight(self.bait.get(acc, {}), now, timedelta(days=7))
        in_eps = self._weight(self.episode_payee.get(acc, {}), now, timedelta(days=7))
        fanin_6h = sum(1 for a in self.inn.get(acc, ()) if a.startswith("u:")
                       and (e := self.edges.get((a, acc))) and e.last_ts and now - e.last_ts <= timedelta(hours=6))
        payers = {a for a in self.inn.get(acc, ()) if a.startswith("u:")}
        senders = [s for s, users in self.bait.items() if s != acc and payers & set(users)]
        shared = any(len(payers & set(self.bait[s])) >= 2 for s in senders)
        loop, path = self.money_loop(acc, senders)
        hubs = self.known_cashouts(exclude=acc)
        forwards = any(b in hubs for b in self.out.get(acc, ()) if "bank_flows" in self.edges[(acc, b)].sources)
        crowd = (fanout >= CROWD_BAIT_USERS or in_eps >= CROWD_EPISODE_USERS or fanin_6h >= CROWD_FANIN_6H or shared)
        return {"bait_sender_fanout_7d": fanout, "payee_in_episodes_7d": in_eps, "payee_fanin_ruko_6h": fanin_6h,
                "shared_bait_sender": shared, "money_loop": loop, "loop_path": path,
                "forwards_to_known_cashout": forwards, "crowd": crowd}

    def money_loop(self, payee: str, senders: list[str]) -> tuple[Optional[bool], Optional[str]]:
        """True when the payee and a bait sender forward to the same account (2 hops), or money flows
        payee -> ... -> bait sender within 3 hops. False only when the payee's bank flows were visible
        and showed no link; None when they could not be seen."""
        visible = self.flows_seen.get(payee)
        if visible is None:
            return None, None
        p_out = {b for b in self.out.get(payee, ()) if "bank_flows" in self.edges[(payee, b)].sources}
        for s in senders:
            s_out = {b for b in self.out.get(s, ()) if "bank_flows" in self.edges[(s, b)].sources}
            common = p_out & s_out
            if common:
                hub = sorted(common)[0]
                return True, f"{payee} -> {hub} <- {s}"
            path = self._path(payee, s, 3)
            if path:
                return True, " -> ".join(path)
        return False, None

    def _path(self, a: str, b: str, hops: int) -> Optional[list[str]]:
        frontier = [[a]]
        for _ in range(hops):
            nxt = []
            for p in frontier:
                for n in self.out.get(p[-1], ()):
                    if n == b:
                        return p + [n]
                    if n not in p and not n.startswith("u:"):
                        nxt.append(p + [n])
            frontier = nxt
        return None

    def known_cashouts(self, exclude: str = "") -> set[str]:
        """Accounts that at least two flagged payees forward to."""
        flagged = {a for a, m in self.marks.items() if m.get("flagged") and a != exclude}
        counts: dict[str, int] = defaultdict(int)
        for p in flagged:
            for b in self.out.get(p, ()):
                if "bank_flows" in self.edges[(p, b)].sources:
                    counts[b] += 1
        return {b for b, c in counts.items() if c >= 2}

    # ---------- reads for the console (C5) ----------

    def neighbourhood(self, account: str, hops: int = 2) -> dict:
        start = account.strip().lower()
        nodes, frontier = {start}, {start}
        for _ in range(hops):
            nxt = set()
            for n in frontier:
                nxt |= self.out.get(n, set()) | self.inn.get(n, set())
            nxt -= nodes
            nodes |= nxt
            frontier = nxt
        edges = [{"from": a, "to": b, "n": e.n, "inr": round(e.inr, 2), "sources": sorted(e.sources),
                  "last_ts": e.last_ts.isoformat() if e.last_ts else None}
                 for (a, b), e in self.edges.items() if a in nodes and b in nodes]
        return {"center": start, "nodes": [{"id": n, "kind": "ruko_user" if n.startswith("u:") else "account",
                                            "marks": self.marks.get(n, {})} for n in sorted(nodes)],
                "edges": edges}
