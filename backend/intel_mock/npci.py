"""Mock NPCI: the UPI switch. Resolves a UPI ID to its bank and the public payee details.

What any UPI app really gets back from NPCI: registered name, person or merchant, MCC, verified
merchant flag. Never account age, balances or risk -- those stay inside the payee's bank.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from sim.config import P2P_TXN_CAP

router = APIRouter(prefix="/npci", tags=["NPCI (mock)"])


def _store(request: Request):
    return request.app.state.store


@router.get("/resolve/{upi_id}")
def resolve(upi_id: str, request: Request) -> dict:
    s = _store(request)
    upi_id = upi_id.strip().lower()
    if "@" not in upi_id:
        raise HTTPException(400, {"valid": False, "reason": "malformed_vpa"})
    handle = upi_id.rsplit("@", 1)[1]
    h = s.handles.get(handle)
    if h is None:
        raise HTTPException(404, {"valid": False, "reason": "unknown_handle"})
    acct = s.account_at(upi_id, s.now)
    if acct is None:
        raise HTTPException(404, {"valid": False, "reason": "no_such_vpa"})
    return {
        "valid": True, "upi_id": upi_id, "registered_name": acct["holder_name"],
        "holder_type": acct["holder_type"], "mcc": acct["mcc"],
        "verified_merchant": bool(acct["verified"]) if acct["holder_type"] == "merchant" else False,
        "handle": handle, "psp_app": h["app"], "bank": acct["bank"], "bank_code": acct["bank_code"],
    }


@router.get("/mapper/{mobile}")
def mapper(mobile: str, request: Request) -> dict:
    """UPI number mapper: a mobile number to the UPI ID linked to it."""
    s = _store(request)
    acct = s.by_mobile.get(mobile.strip())
    if acct is None or acct["created_at"] > s.now:
        raise HTTPException(404, {"mapped": False})
    # Like a real UPI app, the payer sees the name the account is registered in before paying.
    return {"mapped": True, "mobile": acct["mobile"], "upi_id": acct["upi_id"], "registered_name": acct["holder_name"]}


class PayRequest(BaseModel):
    from_upi: str
    to_upi: str
    amount: float = Field(gt=0)
    ts: Optional[datetime] = None


@router.post("/pay")
def pay(req: PayRequest, request: Request) -> dict:
    """Live payment for demos (mule pump, the phone). Writes to the in-memory ledger only."""
    s = _store(request)
    for upi in (req.from_upi, req.to_upi):
        if s.account_at(upi, s.now) is None:
            raise HTTPException(404, {"status": "FAILED", "reason": f"no_such_vpa:{upi}"})
    if req.amount > P2P_TXN_CAP:
        raise HTTPException(400, {"status": "FAILED", "reason": "over_txn_limit"})
    ts = req.ts or s.now
    if ts > s.now:
        s.set_clock(ts)
    s.add_payment(ts, req.from_upi, req.to_upi, req.amount)
    return {"status": "SUCCESS", "tx_id": f"live_{s.live_payments:06d}", "ts": ts.isoformat()}
