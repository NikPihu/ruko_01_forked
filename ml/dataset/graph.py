"""graph.store.GraphStore with faster expiry and "paid before" lookups, for replaying whole worlds.

On every /v1/decide the engine calls GraphStore.expire(now), which scans every edge and every
payment, and GraphStore.paid_before(), which scans every payment into the payee. That is fine for a
live demo, but a replay of 360,000 payments would take hours. This subclass keeps heaps of expiry
times and an index of completed payments, and gives exactly the same answers
(tests/test_graph_expiry.py checks it against the original).
"""
from __future__ import annotations

import heapq
from collections import defaultdict
from datetime import datetime
from typing import Optional

from graph.store import KEEP, GraphStore, user_node


class ReplayGraphStore(GraphStore):
    def __init__(self) -> None:
        super().__init__()
        self._edge_heap: list[tuple[datetime, str, str]] = []
        self._payment_heap: list[tuple[datetime, str]] = []
        self._completed: dict[tuple[str, str], list[datetime]] = defaultdict(list)  # (user node, payee) -> times

    def reset(self) -> None:
        self.__init__()

    # ---------- keep the heaps and the index in step with every write ----------

    def _push_edge(self, key: tuple[str, str]) -> None:
        e = self.edges.get(key)
        if e is not None and e.last_ts is not None and not e.protected:
            heapq.heappush(self._edge_heap, (e.last_ts, *key))

    def _edge(self, a: str, b: str, inr: float, ts: datetime, source: str) -> None:
        super()._edge(a, b, inr, ts, source)
        self._push_edge((a, b))

    def add_bank_flows(self, account: str, flows: Optional[dict]) -> None:
        super().add_bank_flows(account, flows)
        if flows is not None:
            acc = account.strip().lower()
            for o in flows.get("outbound", []):
                self._push_edge((acc, o["upi_id"].strip().lower()))

    def add_payment(self, user_id: str, payee: str, inr: float, ts: datetime, request_id: Optional[str] = None) -> None:
        new = bool(request_id) and request_id not in self.payments
        super().add_payment(user_id, payee, inr, ts, request_id=request_id)
        if new:
            heapq.heappush(self._payment_heap, (ts, request_id))

    def record_outcome(self, request_id: str, user_id: str, payee: str, inr: float, status: str,
                       ts: datetime) -> tuple[str, bool]:
        held, recorded = super().record_outcome(request_id, user_id, payee, inr, status, ts)
        p = self.payments.get(request_id)
        if p is not None:
            heapq.heappush(self._payment_heap, (p.outcome_ts or p.ts, request_id))
            self._push_edge((p.user, p.payee))  # a completed payment can move the edge's last_ts
            if recorded and p.status == "completed":
                self._completed[(p.user, p.payee)].append(p.outcome_ts or p.ts)
        return held, recorded

    # ---------- the same answers, without full scans ----------

    def expire(self, now: datetime) -> None:
        cutoff = now - KEEP
        while self._edge_heap and self._edge_heap[0][0] < cutoff:
            ts, a, b = heapq.heappop(self._edge_heap)
            e = self.edges.get((a, b))
            # Skip stale heap entries: the edge was seen again later, deleted, or protected.
            if e is None or e.protected or e.last_ts != ts:
                continue
            del self.edges[(a, b)]
            self.out[a].discard(b)
            self.inn[b].discard(a)
        while self._payment_heap and self._payment_heap[0][0] < cutoff:
            ts, rid = heapq.heappop(self._payment_heap)
            p = self.payments.get(rid)
            if p is None or (p.outcome_ts or p.ts) != ts:
                continue
            del self.payments[rid]
            ids = self.payments_into.get(p.payee)
            if ids and rid in ids:
                ids.remove(rid)
            if p.status == "completed":
                times = self._completed[(p.user, p.payee)]
                times.remove(ts)

    def paid_before(self, user_id: str, payee: str, before: datetime) -> bool:
        times = self._completed.get((user_node(user_id), payee.strip().lower()))
        return bool(times) and min(times) < before
