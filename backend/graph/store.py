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

    def story(self, account: str, now: datetime, max_side: int = 6) -> dict:
        """One account's money flow as a short left-to-right story for analysts:
        bait senders -> RUKO users (one group) -> payees -> where the payees send money on,
        plus any link back to a bait sender (the money loop) and plain-English sentences."""
        acc = account.strip().lower()
        known = acc in self.out or acc in self.inn
        if self.bait.get(acc):
            role = "bait_sender"
            senders = [acc]
            baited = set(self.bait[acc])
            paid_by: dict[str, set[str]] = defaultdict(set)
            for u in baited:
                for b in self.out.get(u, ()):
                    if not b.startswith("u:") and b != acc:
                        paid_by[b].add(u)
            payees = sorted((p for p, us in paid_by.items()
                             if len(us) >= 2 or self.marks.get(p, {}).get("flagged")),
                            key=lambda p: (-len(paid_by[p]), p))[:max_side]
            payers = set().union(*(paid_by[p] for p in payees)) if payees else set()
        else:
            role = "payee" if any(a.startswith("u:") for a in self.inn.get(acc, ())) else (
                "account" if known else "unknown")
            payees = [acc]
            payers = {a for a in self.inn.get(acc, ()) if a.startswith("u:")}
            senders = sorted((s for s, us in self.bait.items() if s != acc and payers & set(us)),
                             key=lambda s: (-len(payers & set(self.bait[s])), s))[:max_side]
            baited = set().union(*(set(self.bait[s]) for s in senders)) if senders else set()
        users = baited | payers

        def node(account_id: str, **extra) -> dict:
            return {"id": account_id, "marks": self.marks.get(account_id, {}), **extra}

        def bank_out(a: str) -> list[tuple[str, Edge]]:
            return [(b, self.edges[(a, b)]) for b in self.out.get(a, ())
                    if "bank_flows" in self.edges[(a, b)].sources]

        links: list[dict] = []
        for s in senders:
            us = set(self.bait[s]) & users
            inr = sum(self.edges[(s, u)].inr for u in us if (s, u) in self.edges)
            links.append({"from": s, "to": "users", "kind": "bait", "users": len(us), "inr": round(inr, 2)})
        payee_nodes = []
        for p in payees:
            us = {u for u in self.inn.get(p, ()) if u.startswith("u:")} & users
            es = [self.edges[(u, p)] for u in us if (u, p) in self.edges]
            n, inr = sum(e.n for e in es), round(sum(e.inr for e in es), 2)
            payee_nodes.append(node(p, users=len(us), payments=n, inr=inr))
            if us:
                links.append({"from": "users", "to": p, "kind": "pay", "users": len(us), "n": n, "inr": inr})

        cash: dict[str, dict] = {}
        for p in payees:
            for b, e in sorted(bank_out(p), key=lambda x: -x[1].inr):
                if b in senders:
                    links.append({"from": p, "to": b, "kind": "loop", "n": e.n, "inr": round(e.inr, 2),
                                  "hold_min": e.hold_min})
                    continue
                c = cash.setdefault(b, node(b, inr=0.0, n=0, hold_min=e.hold_min))
                c["inr"] = round(c["inr"] + e.inr, 2)
                c["n"] += e.n
                links.append({"from": p, "to": b, "kind": "forward", "n": e.n, "inr": round(e.inr, 2),
                              "hold_min": e.hold_min})
        cashouts = sorted(cash.values(), key=lambda c: -c["inr"])[:max_side]
        keep = {c["id"] for c in cashouts}
        links = [lk for lk in links if lk["kind"] != "forward" or lk["to"] in keep]
        # A bait sender that sends money to the same place as a payee: shared cash-out (also a loop).
        for s in senders:
            for b, e in bank_out(s):
                if b in keep:
                    links.append({"from": s, "to": b, "kind": "shared", "n": e.n, "inr": round(e.inr, 2)})

        centre_payee = acc if role != "bait_sender" else (payees[0] if payees else None)
        loop, path = (self.money_loop(centre_payee, senders) if centre_payee else (None, None))
        signals = self.account_signals(acc, now)
        return {"center": acc, "center_role": role, "known": known or role == "bait_sender",
                "senders": [node(s, users_baited=len(set(self.bait[s]) & users)) for s in senders],
                "users": {"count": len(users), "baited": len(baited), "paid": len(payers)},
                "payees": payee_nodes, "cashouts": cashouts, "links": links,
                "loop": {"found": loop, "path": path},
                "flows_visible": self.flows_seen.get(centre_payee) if centre_payee else None,
                "signals": signals,
                "summary": _story_sentences(role, acc, senders, baited, payers, payee_nodes, cashouts,
                                            links, loop, self.flows_seen.get(centre_payee) if centre_payee else None,
                                            self.marks.get(acc, {}))}

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


def _inr(x: float) -> str:
    """Indian digit grouping: 1450329 -> Rs 14,50,329."""
    n = str(int(round(x)))
    if len(n) > 3:
        head, tail = n[:-3], n[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        n = ",".join(([head] if head else []) + groups + [tail])
    return "₹" + n


def _story_sentences(role: str, acc: str, senders: list[str], baited: set, payers: set, payees: list[dict],
                     cashouts: list[dict], links: list[dict], loop, flows_visible, marks: dict) -> list[str]:
    """The story in words, for an analyst who has never seen a graph."""
    out: list[str] = []
    if role == "unknown":
        return [f"RUKO has not seen any money move to or from {acc} yet."]
    bait_links = {lk["from"]: lk for lk in links if lk["kind"] == "bait"}
    if role == "bait_sender":
        lk = bait_links.get(acc, {})
        each = f", about {_inr(lk['inr'] / lk['users'])} each" if lk.get("users") and lk.get("inr") else ""
        out.append(f"{acc} sent small “rewards” to {len(baited)} RUKO users{each}.")
        if payees:
            top = payees[0]
            out.append(f"{len(payers)} of those users then paid new accounts; most often {top['id']} "
                       f"({top['users']} users, {_inr(top['inr'])}).")
    else:
        p = payees[0] if payees else {"users": 0, "payments": 0, "inr": 0}
        if senders:
            s = senders[0]
            more = f" (and {len(senders) - 1} more account{'s' if len(senders) > 2 else ''})" if len(senders) > 1 else ""
            out.append(f"{s}{more} sent small “rewards” to {len(baited)} RUKO users.")
            out.append(f"{p['users']} of them then paid {acc}: {_inr(p['inr'])} in {p['payments']} payments.")
        elif p["users"]:
            out.append(f"{p['users']} RUKO users paid {acc}: {_inr(p['inr'])} in {p['payments']} payments.")
    if cashouts:
        holds = [c["hold_min"] for c in cashouts if c.get("hold_min") is not None]
        when = f", usually within {min(holds):.0f} minutes" if holds else ""
        who = acc if role != "bait_sender" else "These accounts"
        out.append(f"{who} moved {_inr(sum(c['inr'] for c in cashouts))} on to {len(cashouts)} "
                   f"other account{'s' if len(cashouts) > 1 else ''}{when}.")
    if loop is True:
        back = [lk for lk in links if lk["kind"] in ("loop", "shared")]
        out.append("Money flows back to the account that paid the “rewards”: the earnings came from the "
                   "same ring the victims are paying." if back else
                   "The payee and the “rewards” account send money to the same place: one ring.")
    elif loop is None and role != "bait_sender" and senders:
        out.append("Where this account sends money is not visible: its bank does not share data, "
                   "so a money loop can't be checked.")
    elif flows_visible and not cashouts and role != "bait_sender":
        out.append("Its bank shares data and shows no onward payments.")
    if marks.get("listed"):
        out.append("It is already reported on the I4C registry or rated high risk by DoT.")
    elif role != "bait_sender" and (senders or marks.get("flagged")):
        out.append("It is not on any fraud registry yet: RUKO found it from its payments alone.")
    return out
