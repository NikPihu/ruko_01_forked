"""Find new mules and their rings from the payment graph (docs/task-scam-watcher.md §9.5).

Runs every hour in the demo (weekly in a real deployment) and produces a suspect list for analysts,
not automatic blocks:
1. Seeds: accounts with strong evidence (registry-listed, a flagged payee in a high-risk episode,
   or analyst-confirmed).
2. Spread suspicion from the seeds along money edges with personalised PageRank. Weights are
   proportional to the amount (so a mule's small "cover" payments to ordinary people carry little
   suspicion, its big forwards to cash-out accounts carry most) and double for fast forwarding.
3. Rings: connected groups among suspects and seeds; hubs are accounts many of them forward to.
4. Each suspect gets a band, a reason in words, an evidence path and a ring id.
5. A suspect only affects live scoring after two different analysts approve it (§9.5 step 5).
"""
from __future__ import annotations

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
    """Undirected weights between accounts, proportional to the money. Users are pass-through: two
    accounts paid in the same victim's episode are linked through that victim, but a victim is never
    a suspect. (Log-scaled weights flagged a mule's cover payees almost like its cash-out accounts:
    precision of medium and high suspects 16% against 38% with linear weights in the eval world.)"""
    w: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for (a, b), e in g.edges.items():
        x = e.inr * (2.0 if e.hold_min is not None and e.hold_min <= 30 else 1.0)
        if "bank_flows" not in e.sources and not (a.startswith("u:") or b.startswith("u:")):
            x *= 0.5
        w[a][b] += x
        w[b][a] += x
    return w


def seeds(g: GraphStore, reviews: dict[str, Review]) -> dict[str, str]:
    out = {}
    for acc, m in g.marks.items():
        if m.get("listed"):
            out[acc] = "registry-listed"
        elif m.get("flagged"):
            out[acc] = "flagged in a high-risk episode"
        elif m.get("interrupted"):
            out[acc] = f"the payee of a payment RUKO stopped ({m['interrupted']}) for mule-like evidence"
    for acc, r in reviews.items():
        if r.approved:
            out[acc] = "confirmed by analysts"
    return out


BAND_RANK = {"low": 0, "med": 1, "high": 2}


def discover(g: GraphStore, reviews: dict[str, Review], now: datetime, min_band: str = "low") -> list[dict]:
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
        band = next(b for t, b in BANDS if rel >= t)
        if BAND_RANK[band] < BAND_RANK[min_band]:
            continue
        why, path = _why(g, w, n, seed, hubs)
        e_first = [e.first_ts for (a, b), e in g.edges.items() if (a == n or b == n) and e.first_ts]
        rv = reviews.get(n)
        auto = g.automation(n, now)
        out.append({
            "upi_id": n, "band": band, "score": round(rel, 3),
            "why": why, "evidence_path": path, "ring_id": rings.get(n),
            "is_hub": n in hubs, "first_seen": min(e_first).isoformat() if e_first else None,
            "registry_listed": bool(g.marks.get(n, {}).get("listed")),
            "automated": bool(auto["automated"]), "automation_why": auto.get("why"),
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


# ---------- ring view for the analyst console ----------

def hub_score(g: GraphStore, acc: str, members: set[str], now: datetime) -> dict:
    """How much an account behaves like a ring hub, 0..1, from four plain parts:
    fan-in (distinct accounts and users paying it), pass-through (money out / money in),
    speed (money leaves within 30 minutes) and links to other ring members."""
    payers = {a for a in g.inn.get(acc, ())}
    inr_in = sum(g.edges[(a, acc)].inr for a in payers if (a, acc) in g.edges)
    outs = {b for b in g.out.get(acc, ())}
    inr_out = sum(g.edges[(acc, b)].inr for b in outs if (acc, b) in g.edges)
    holds = [g.edges[(acc, b)].hold_min for b in outs if (acc, b) in g.edges and g.edges[(acc, b)].hold_min is not None]
    links = len((payers | outs) & members)
    parts = {
        "fan_in": min(1.0, len(payers) / 20),
        "pass_through": min(1.0, inr_out / inr_in) if inr_in else 0.0,
        "speed": 1.0 if holds and min(holds) <= 30 else 0.0,
        "ring_links": min(1.0, links / 3),
    }
    return {"score": round(sum(parts.values()) / len(parts), 3), "parts": parts,
            "payers": len(payers), "inr_in": round(inr_in, 2), "inr_out": round(inr_out, 2),
            "fastest_hold_min": min(holds) if holds else None}


def _inr(x: float) -> str:
    return f"₹{x:,.0f}"


def _source(e) -> str:
    return "its bank's flow data" if "bank_flows" in e.sources else "payments RUKO checked"


def _link_words(g: GraphStore, a: str, members: set[str], seed: dict[str, str]) -> Optional[str]:
    """How one account is tied to the rest of the ring, strongest evidence first."""
    money = []
    for (x, y), e in g.edges.items():
        if x == a and y in members:
            money.append((e.inr, f"sent {_inr(e.inr)} to {y}", e))
        elif y == a and x in members:
            money.append((e.inr, f"received {_inr(e.inr)} from {x}", e))
    if money:
        inr, words, e = max(money, key=lambda t: t[0])
        fast = f", passed on within {e.hold_min:.0f} min" if e.hold_min is not None and e.hold_min <= 30 else ""
        return f"{words}{fast} ({_source(e)})"
    users = {u for (u, y) in g.edges if u.startswith("u:") and y == a}
    for m in sorted(members - {a}, key=lambda m: m not in seed):
        shared = users & {u for (u, y) in g.edges if u.startswith("u:") and y == m}
        if shared:
            return f"{len(shared)} RUKO user{'s' if len(shared) > 1 else ''} paid both it and {m}"
    return None


def explain_ring(g: GraphStore, accs: list[str], seed: dict[str, str], hubs: set[str],
                 victims: int, money_in: float, fastest: Optional[float]) -> dict:
    """The ring in plain words for the analyst: where discovery started, how each member is tied in,
    where the money goes, and what happens next. Facts only; nothing here changes a payment."""
    members = set(accs)
    start = [{"upi_id": a, "why": seed[a]} for a in sorted(accs) if a in seed]
    linked = {a: _link_words(g, a, members, seed) for a in sorted(accs) if a not in seed}
    steps = []
    if start:
        steps.append("Started from " + "; ".join(f"{x['upi_id']} ({x['why']})" for x in start) + ".")
    for a, words in linked.items():
        if words:
            steps.append(f"{a} joined because it {words}.")
    seeds_in = [x["upi_id"] for x in start]
    for i, a in enumerate(seeds_in[1:], 1):
        words = _link_words(g, a, set(seeds_in[:i]), seed)
        if words:
            steps.append(f"The starting accounts are tied together: {a} {words}.")
    ring_hubs = sorted(h for h in hubs & members if any(y == h and x in members for (x, y) in g.edges))
    if ring_hubs:
        steps.append(f"{len(ring_hubs)} hub{'s' if len(ring_hubs) > 1 else ''} ({', '.join(ring_hubs)}): several ring "
                     "accounts send money to each, the usual shape of cash-out accounts.")
    if victims:
        steps.append(f"{victims} RUKO user{'s' if victims > 1 else ''} paid {_inr(money_in)} into the ring"
                     + (f"; the fastest account passed money on within {fastest:.0f} min." if fastest is not None else "."))
    steps.append("Suspects count in live payment checks only after two different analysts approve them.")
    return {"started_from": start, "linked_by": linked, "steps": steps}


def ring_view(g: GraphStore, reviews: dict[str, Review], now: datetime) -> list[dict]:
    """Every ring with its members, hubs, victims, money and speed (analyst console)."""
    suspects = {s["upi_id"]: s for s in discover(g, reviews, now, min_band="low")}
    seed = seeds(g, reviews)
    members_all = set(suspects) | set(seed)
    ring_of = _rings(g, members_all)
    hubs = _hubs(g, members_all)
    rings: dict[str, list[str]] = defaultdict(list)
    for acc, rid in ring_of.items():
        rings[rid].append(acc)
    out = []
    for rid, accs in rings.items():
        members = set(accs)
        accounts = []
        for a in sorted(accs):
            h = hub_score(g, a, members, now)
            auto = g.automation(a, now)
            s = suspects.get(a)
            accounts.append({
                "upi_id": a,
                "role": "seed" if a in seed else "suspect",
                "why": seed.get(a) or (s["why"] if s else None),
                "band": s["band"] if s else None,
                "is_hub": a in hubs or h["score"] >= 0.6,
                "hub_score": h["score"], "hub_parts": h["parts"],
                "payers": h["payers"], "inr_in": h["inr_in"], "inr_out": h["inr_out"],
                "fastest_hold_min": h["fastest_hold_min"],
                "automated": bool(auto["automated"]), "automation_why": auto.get("why"),
                "registry_listed": bool(g.marks.get(a, {}).get("listed")),
                "approved": bool(reviews.get(a) and reviews[a].approved),
                "linked_by": None if a in seed else _link_words(g, a, members, seed),
            })
        victims = {u for (u, b) in g.edges if u.startswith("u:") and b in members}
        baited = {u for (a, u) in g.edges if a in members and u.startswith("u:")}
        links = [{"from": a, "to": b, "inr": round(e.inr, 2), "n": e.n,
                  "hold_min": e.hold_min, "sources": sorted(e.sources)}
                 for (a, b), e in g.edges.items() if a in members and b in members]
        victim_links = defaultdict(int)
        for (u, b) in g.edges:
            if u.startswith("u:") and b in members:
                victim_links[b] += 1
        money_in = sum(e.inr for (u, b), e in g.edges.items() if u.startswith("u:") and b in members)
        holds = [x["fastest_hold_min"] for x in accounts if x["fastest_hold_min"] is not None]
        out.append({
            "ring_id": rid, "size": len(accs), "accounts": sorted(accounts, key=lambda x: -x["hub_score"]),
            "hubs": [x["upi_id"] for x in accounts if x["is_hub"]],
            "victims": len(victims), "baited_users": len(baited),
            "money_from_victims_inr": round(money_in, 2),
            "fastest_hold_min": min(holds) if holds else None,
            "automated": any(x["automated"] for x in accounts),
            "links": links, "victims_per_account": dict(victim_links),
            "explanation": explain_ring(g, accs, seed, hubs, len(victims), money_in, min(holds) if holds else None),
            "summary": (f"{len(accs)} accounts, {len(victims)} RUKO users paid into it"
                        + (f", {len(baited)} got 'rewards' from it" if baited else "")
                        + (f"; money leaves within {min(holds):.0f} min" if holds else "")
                        + ("; runs at bot scale" if any(x["automated"] for x in accounts) else "")),
        })
    return sorted(out, key=lambda r: (-r["victims"], -r["size"]))
