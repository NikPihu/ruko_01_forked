"""Intel adapter: asks NPCI, the payee's bank, DoT FRI and the I4C registry, all within one budget.

Order of calls (as a payment app would really do it):
    NPCI resolve(upi_id) ──▶ bank_code ──▶ bank payee-risk          (two hops, sequential)
    I4C registry(upi_id), registry(caller), FRI(caller), FRI(payee number)   (in parallel from t=0)
Anything that doesn't answer inside the budget, errors, or isn't shared is recorded as unknown,
never as safe.

The same payment must get the same answer, so a slow source is not a coin toss:
    - a lookup that misses the budget keeps running in the background (up to BACKGROUND_CAP_S) and
      its answer is cached for the next payment, instead of being thrown away;
    - when a source misses the budget but answered in the last STALE_S, that answer is used and
      its status says so ("cached:ok"). Older or never-seen answers stay "timeout" (unknown);
    - two payments asking the same thing at once share one request.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote

import httpx

NUMBER_UPI = re.compile(r"^([6-9]\d{9})@")
STALE_S = 30 * 60          # a payee's bank / registry answer from the last 30 minutes still counts
BACKGROUND_CAP_S = 5.0     # a lookup left running after the budget gives up after this long


@dataclass
class IntelResult:
    npci: Optional[dict] = None
    bank: Optional[dict] = None
    payee_registry: Optional[dict] = None
    payee_fri: Optional[dict] = None
    caller_registry: Optional[dict] = None
    caller_fri: Optional[dict] = None
    # Per source: ok | not_found | not_shared | timeout | error | skipped, or "cached:<status>" for
    # an earlier answer (within STALE_S) used because the source missed this payment's budget
    status: dict[str, str] = field(default_factory=dict)
    ms: float = 0.0

    @property
    def vpa_invalid(self) -> bool:
        return self.status.get("npci") in ("not_found", "cached:not_found")


class IntelAdapter:
    def __init__(self, client: httpx.AsyncClient, budget_s: float = 0.15, cache_ttl_s: float = 10.0,
                 stale_s: float = STALE_S):
        self.client = client
        self.budget_s = budget_s
        self.cache_ttl_s = cache_ttl_s
        self.stale_s = stale_s
        # path -> (fresh until, fetched at, status, body); monotonic seconds
        self._cache: dict[str, tuple[float, float, str, Optional[dict]]] = {}
        self._inflight: dict[str, asyncio.Future] = {}

    async def _fetch(self, path: str) -> tuple[str, Optional[dict]]:
        try:
            r = await asyncio.wait_for(self.client.get(path), timeout=BACKGROUND_CAP_S)
        except (httpx.HTTPError, asyncio.TimeoutError):
            return "error", None
        if r.status_code == 200:
            out = ("ok", r.json())
        elif r.status_code == 404:
            out = ("not_found", None)
        elif r.status_code == 403:
            out = ("not_shared", None)
        else:
            return "error", None
        now = time.monotonic()
        self._cache[path] = (now + self.cache_ttl_s, now, *out)
        return out

    async def _get(self, path: str) -> tuple[str, Optional[dict]]:
        hit = self._cache.get(path)
        if hit and hit[0] > time.monotonic():
            return hit[2], hit[3]
        task = self._inflight.get(path)
        if task is None:
            task = self._inflight[path] = asyncio.ensure_future(self._fetch(path))
            task.add_done_callback(lambda _t, p=path: self._inflight.pop(p, None))
        # Shielded: a payment that stops waiting does not stop the lookup; its answer is cached.
        return await asyncio.shield(task)

    def _recent(self, path: Optional[str]) -> Optional[tuple[str, Optional[dict]]]:
        """The last answer for this path if it is at most stale_s old."""
        hit = self._cache.get(path) if path else None
        if hit and time.monotonic() - hit[1] <= self.stale_s:
            return hit[2], hit[3]
        return None

    async def _bank_after_resolve(self, resolve: asyncio.Future) -> tuple[str, Optional[dict]]:
        status, body = await asyncio.shield(resolve)
        if status != "ok":
            return "skipped", None
        return await self._get(f"/banks/{body['bank_code']}/payee-risk/{quote(body['upi_id'])}")

    async def flows(self, upi_id: str, budget_s: float = 1.0) -> Optional[dict]:
        """Where an account forwards money, from its bank (§9.1). None when the bank does not share."""
        upi = upi_id.strip().lower()

        async def go() -> Optional[dict]:
            status, body = await self._get(f"/npci/resolve/{quote(upi)}")
            if status != "ok":
                return None
            status, body = await self._get(f"/banks/{body['bank_code']}/payee-flows/{quote(upi)}")
            return body if status == "ok" else None

        try:
            return await asyncio.wait_for(go(), timeout=budget_s)
        except asyncio.TimeoutError:
            return None

    async def lookup(self, payee_upi: str, caller_number: Optional[str] = None,
                     budget_s: Optional[float] = None) -> IntelResult:
        t0 = time.perf_counter()
        upi = payee_upi.strip().lower()
        resolve_path = f"/npci/resolve/{quote(upi)}"
        paths: dict[str, Optional[str]] = {"npci": resolve_path, "bank": None,
                                           "payee_registry": f"/i4c/registry?upi_id={quote(upi)}"}
        m = NUMBER_UPI.match(upi)
        if m:  # number-based UPI ID: the payee's own phone number can be checked too
            paths["payee_fri"] = f"/dot/fri/{quote('+91' + m.group(1))}"
        if caller_number:
            paths["caller_registry"] = f"/i4c/registry?mobile={quote(caller_number)}"
            paths["caller_fri"] = f"/dot/fri/{quote(caller_number)}"

        resolve = asyncio.ensure_future(self._get(resolve_path))
        tasks: dict[str, asyncio.Future] = {"npci": resolve, "bank": asyncio.ensure_future(self._bank_after_resolve(resolve))}
        for name, path in paths.items():
            if name not in tasks:
                tasks[name] = asyncio.ensure_future(self._get(path))

        await asyncio.wait(tasks.values(), timeout=budget_s or self.budget_s)
        # Unfinished lookups are left to finish in the background and fill the cache.
        for t in tasks.values():
            if not t.done():
                t.add_done_callback(lambda f: f.cancelled() or f.exception())
        # The bank's address needs NPCI's answer: this payment's, or a recent one.
        npci_now = resolve.result() if resolve.done() and not resolve.exception() else self._recent(resolve_path)
        if npci_now and npci_now[0] == "ok":
            body = npci_now[1]
            paths["bank"] = f"/banks/{body['bank_code']}/payee-risk/{quote(body['upi_id'])}"

        res = IntelResult()
        for name, task in tasks.items():
            if task.done() and not task.cancelled() and task.exception() is None:
                status, body = task.result()
            elif (old := self._recent(paths.get(name))) is not None:
                status, body = f"cached:{old[0]}", old[1]
            else:
                status, body = "timeout", None
            res.status[name] = status
            setattr(res, name, body)
        res.ms = round((time.perf_counter() - t0) * 1000, 1)
        return res
