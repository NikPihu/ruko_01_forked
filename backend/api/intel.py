"""Intel adapter: asks NPCI, the payee's bank, DoT FRI and the I4C registry, all within one budget.

Order of calls (as a payment app would really do it):
    NPCI resolve(upi_id) ──▶ bank_code ──▶ bank payee-risk          (two hops, sequential)
    I4C registry(upi_id), registry(caller), FRI(caller), FRI(payee number)   (in parallel from t=0)
Anything that doesn't answer inside the budget, errors, or isn't shared is recorded as unknown,
never as safe.
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


@dataclass
class IntelResult:
    npci: Optional[dict] = None
    bank: Optional[dict] = None
    payee_registry: Optional[dict] = None
    payee_fri: Optional[dict] = None
    caller_registry: Optional[dict] = None
    caller_fri: Optional[dict] = None
    # Per source: ok | not_found | not_shared | timeout | error | skipped
    status: dict[str, str] = field(default_factory=dict)
    ms: float = 0.0

    @property
    def vpa_invalid(self) -> bool:
        return self.status.get("npci") == "not_found"


class IntelAdapter:
    def __init__(self, client: httpx.AsyncClient, budget_s: float = 0.15, cache_ttl_s: float = 10.0):
        self.client = client
        self.budget_s = budget_s
        self.cache_ttl_s = cache_ttl_s
        self._cache: dict[str, tuple[float, str, Optional[dict]]] = {}

    async def _get(self, path: str) -> tuple[str, Optional[dict]]:
        hit = self._cache.get(path)
        if hit and hit[0] > time.monotonic():
            return hit[1], hit[2]
        try:
            r = await self.client.get(path)
        except httpx.HTTPError:
            return "error", None
        if r.status_code == 200:
            out = ("ok", r.json())
        elif r.status_code == 404:
            out = ("not_found", None)
        elif r.status_code == 403:
            out = ("not_shared", None)
        else:
            return "error", None
        if self.cache_ttl_s > 0:
            self._cache[path] = (time.monotonic() + self.cache_ttl_s, *out)
        return out

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
        resolve = asyncio.ensure_future(self._get(f"/npci/resolve/{quote(upi)}"))
        tasks: dict[str, asyncio.Future] = {
            "npci": resolve,
            "bank": asyncio.ensure_future(self._bank_after_resolve(resolve)),
            "payee_registry": asyncio.ensure_future(self._get(f"/i4c/registry?upi_id={quote(upi)}")),
        }
        m = NUMBER_UPI.match(upi)
        if m:  # number-based UPI ID: the payee's own phone number can be checked too
            tasks["payee_fri"] = asyncio.ensure_future(self._get(f"/dot/fri/{quote('+91' + m.group(1))}"))
        if caller_number:
            tasks["caller_registry"] = asyncio.ensure_future(
                self._get(f"/i4c/registry?mobile={quote(caller_number)}"))
            tasks["caller_fri"] = asyncio.ensure_future(self._get(f"/dot/fri/{quote(caller_number)}"))

        done, pending = await asyncio.wait(tasks.values(), timeout=budget_s or self.budget_s)
        for p in pending:
            p.cancel()
        res = IntelResult()
        for name, task in tasks.items():
            if task in done and not task.cancelled() and task.exception() is None:
                status, body = task.result()
            else:
                status, body = "timeout", None
            res.status[name] = status
            setattr(res, name, body)
        res.ms = round((time.perf_counter() - t0) * 1000, 1)
        return res
