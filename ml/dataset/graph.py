"""graph.store.GraphStore with a faster expire(), for replaying hundreds of thousands of payments.

The engine calls GraphStore.expire(now) on every /v1/decide, and it scans every edge each time.
That is fine for a live demo, but a replay of a whole world would take hours. This subclass keeps
a heap of edge expiry times and drops exactly the same edges (not protected, last seen more than
KEEP before `now`); tests/test_graph_expiry.py checks it against the original.
"""
from __future__ import annotations

import heapq
from datetime import datetime
from typing import Optional

from graph.store import KEEP, GraphStore


class ReplayGraphStore(GraphStore):
    def __init__(self) -> None:
        super().__init__()
        self._heap: list[tuple[datetime, str, str]] = []

    def reset(self) -> None:
        self.__init__()

    def _push(self, key: tuple[str, str]) -> None:
        e = self.edges.get(key)
        if e is not None and e.last_ts is not None and not e.protected:
            heapq.heappush(self._heap, (e.last_ts, *key))

    def _edge(self, a: str, b: str, inr: float, ts: datetime, source: str) -> None:
        super()._edge(a, b, inr, ts, source)
        self._push((a, b))

    def add_bank_flows(self, account: str, flows: Optional[dict]) -> None:
        super().add_bank_flows(account, flows)
        if flows is not None:
            acc = account.strip().lower()
            for o in flows.get("outbound", []):
                self._push((acc, o["upi_id"].strip().lower()))

    def expire(self, now: datetime) -> None:
        cutoff = now - KEEP
        while self._heap and self._heap[0][0] < cutoff:
            ts, a, b = heapq.heappop(self._heap)
            e = self.edges.get((a, b))
            # Skip stale heap entries: the edge was seen again later, deleted, or protected.
            if e is None or e.protected or e.last_ts != ts:
                continue
            del self.edges[(a, b)]
            self.out[a].discard(b)
            self.inn[b].discard(a)
