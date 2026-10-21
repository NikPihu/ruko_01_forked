"""Find new mules and their rings from the payment graph (docs/task-scam-watcher.md §9.5).

Runs every hour in the demo (weekly in a real deployment) and produces a suspect list for analysts,
not automatic blocks:
1. Seeds: accounts with strong evidence (registry-listed, a flagged payee in a high-risk episode,
   or analyst-confirmed).
2. Spread suspicion from the seeds along money edges with personalised PageRank. Weights grow with
   the amount, with fast forwarding (short hold) and with fan-in from many RUKO users.
3. Rings: connected groups among suspects and seeds; hubs are accounts many of them forward to.
4. Each suspect gets a band, a reason in words, an evidence path and a ring id.
5. A suspect only affects live scoring after two different analysts approve it (§9.5 step 5).
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from graph.store import GraphStore

DAMPING = 0.85
ITERATIONS = 30
MIN_SCORE = 0.02        # share of the strongest seed's score below which an account is not a suspect
BANDS = ((0.25, "high"), (0.08, "med"), (MIN_SCORE, "low"))
APPROVALS_NEEDED = 2


@dataclass
class Review:
    approved_by: set[str] = field(default_factory=set)
    rejected_by: set[str] = field(default_factory=set)

    @property
    def approved(self) -> bool:
        return len(self.approved_by) >= APPROVALS_NEEDED and not self.rejected_by


def _weights(g: GraphStore) -> dict[str, dict[str, float]]:
    """Undirected weights between accounts. Users are pass-through: two accounts paid in the same
    victim's episode are linked through that victim, but a victim is never a suspect."""
    w: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for (a, b), e in g.edges.items():
        x = math.log1p(e.inr) * (2.0 if e.hold_min is not None and e.hold_min <= 30 else 1.0)
        if "bank_flows" not in e.sources and not (a.startswith("u:") or b.startswith("u:")):
            x *= 0.5
        w[a][b] += x
        w[b][a] += x
    # Fan-in from many RUKO users makes an account a stronger conduit.
    for node, nbrs in w.items():
        if node.startswith("u:"):
            continue
        users = sum(1 for n in nbrs if n.startswith("u:"))
        if users >= 3:
            for n in nbrs:
                nbrs[n] *= 1 + math.log(users)
    return w


def seeds(g: GraphStore, reviews: dict[str, Review]) -> dict[str, str]:
    out = {}
    for acc, m in g.marks.items():
        if m.get("listed"):
            out[acc] = "registry-listed"
        elif m.get("flagged"):
            out[acc] = "flagged in a high-risk episode"
    for acc, r in reviews.items():
        if r.approved:
            out[acc] = "confirmed by analysts"
    return out


def discover(g: GraphStore, reviews: dict[str, Review], now: datetime) -> list[dict]:
    seed = seeds(g, reviews)
    if not seed:
        return []
    w = _weights(g)
    nodes = list(w)
    p = {n: (1.0 / len(seed) if n in seed else 0.0) for n in nodes}
    r = dict(p)
    totals = {n: sum(w[n].values()) or 1.0 for n in nodes}
    for _ in range(ITERATIONS):
        nxt = {n: (1 - DAMPING) * p[n] for n in nodes}
        for n in nodes:
            share = DAMPING * r[n] / totals[n]
            for m, x in w[n].items():
                nxt[m] += share * x
        r = nxt
    top = max(r[s] for s in seed if s in r) if any(s in r for s in seed) else 1.0

    candidates = {}
    for n, score in r.items():
        rel = score / top
        m = g.marks.get(n, {})
        if n.startswith("u:") or n in seed or rel < MIN_SCORE or m.get("verified_merchant"):
            continue
        candidates[n] = rel
    rings = _rings(g, set(candidates) | set(seed))
    hubs = _hubs(g, set(candidates) | set(seed))
    out = []
    for n, rel in sorted(candidates.items(), key=lambda kv: -kv[1]):
        why, path = _why(g, w, n, seed, hubs)
        e_first = [e.first_ts for (a, b), e in g.edges.items() if (a == n or b == n) and e.first_ts]
        rv = reviews.get(n)
        out.append({
            "upi_id": n, "band": next(b for t, b in BANDS if rel >= t), "score": round(rel, 3),
            "why": why, "evidence_path": path, "ring_id": rings.get(n),
            "is_hub": n in hubs, "first_seen": min(e_first).isoformat() if e_first else None,
            "registry_listed": bool(g.marks.get(n, {}).get("listed")),
            "review": {"approved_by": sorted(rv.approved_by), "rejected_by": sorted(rv.rejected_by),
                       "approved": rv.approved} if rv else {"approved_by": [], "rejected_by": [], "approved": False},
        })
    return out


def _why(g: GraphStore, w, n: str, seed: dict[str, str], hubs: set[str]) -> tuple[str, list[str]]:
    # Direct money link to a seed?
    for s in seed:
        if (n, s) in g.edges or (s, n) in g.edges:
            arrow = f"{n} -> {s}" if (n, s) in g.edges else f"{s} -> {n}"
            return f"money moves directly between it and an account {seed[s]}", arrow.split(" -> ")
    # Shared victims with a seed?
    victims = {u for u in w[n] if u.startswith("u:")}
    for s in seed:
        shared = victims & {u for u in w.get(s, {}) if u.startswith("u:")}
        if shared:
            return (f"{len(shared)} RUKO user(s) who paid it also paid an account {seed[s]}",
                    [n, sorted(shared)[0], s])
    fwd = [b for b in g.out.get(n, ()) if b in hubs]
    if fwd:
        return "it forwards money to a hub that other suspect accounts also use", [n, fwd[0]]
    return "it is two or more money hops from known mule accounts", [n]


def _rings(g: GraphStore, members: set[str]) -> dict[str, str]:
    """Connected groups among suspects and seeds (account-to-account edges, and shared victims)."""
    parent = {m: m for m in members}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    for (a, b) in g.edges:
        if a in members and b in members:
            union(a, b)
    by_user: dict[str, list[str]] = defaultdict(list)
    for (a, b) in g.edges:
        if a.startswith("u:") and b in members:
            by_user[a].append(b)
        if b.startswith("u:") and a in members:
            by_user[b].append(a)
    for accs in by_user.values():
        for x in accs[1:]:
            union(accs[0], x)
    groups: dict[str, list[str]] = defaultdict(list)
    for m in members:
        groups[find(m)].append(m)
    ids = {}
    for i, (_, accs) in enumerate(sorted(groups.items(), key=lambda kv: -len(kv[1]))):
        if len(accs) >= 2:
            for a in accs:
                ids[a] = f"ring_{i + 1}"
    return ids


def _hubs(g: GraphStore, members: set[str]) -> set[str]:
    counts: dict[str, int] = defaultdict(int)
    for (a, b), e in g.edges.items():
        if a in members and "bank_flows" in e.sources:
            counts[b] += 1
    return {b for b, c in counts.items() if c >= 2}


def approved_suspects(reviews: dict[str, Review]) -> set[str]:
    return {a for a, r in reviews.items() if r.approved}


def review(reviews: dict[str, Review], upi_id: str, reviewer: str, decision: str) -> Review:
    r = reviews.setdefault(upi_id.strip().lower(), Review())
    (r.approved_by if decision == "approve" else r.rejected_by).add(reviewer)
    if decision == "approve":
        r.rejected_by.discard(reviewer)
    else:
        r.approved_by.discard(reviewer)
    return r


def last_run_summary(suspects: list[dict], now: datetime, error: Optional[str] = None) -> dict:
    return {"ran_at": now.isoformat(), "suspects": len(suspects),
            "rings": len({s["ring_id"] for s in suspects if s["ring_id"]}), "error": error}
