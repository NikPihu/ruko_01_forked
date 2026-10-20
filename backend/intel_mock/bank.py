"""Mock banks: each bank answers risk questions only about its own accounts.

Visibility modes reproduce how much a risk engine at a payment app can really see:
    none     no bank shares payee data (RUKO sees only NPCI's public fields)
    partner  only banks flagged partner share (default; today's reality for most apps)
    dpip     every bank shares, as if RBI's Digital Payments Intelligence Platform were live
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from .payee_features import mulehunter_score, payee_features
from .store import bank_code

router = APIRouter(prefix="/banks", tags=["Banks (mock)"])


@router.get("")
def list_banks(request: Request) -> list[dict]:
    s = request.app.state.store
    seen: dict[str, dict] = {}
    for h in s.handles.values():
        code = bank_code(h["bank"])
        seen.setdefault(code, {"bank_code": code, "bank": h["bank"], "partner": h["partner"],
                               "handles": []})["handles"].append(h["handle"])
    return list(seen.values())


@router.get("/{code}/payee-risk/{upi_id}")
def payee_risk(code: str, upi_id: str, request: Request) -> dict:
    s = request.app.state.store
    upi_id = upi_id.strip().lower()
    acct = s.account_at(upi_id, s.now)
    if acct is None or acct["bank_code"] != code:
        raise HTTPException(404, {"shared": False, "reason": "not_our_account"})
    if s.visibility == "none" or (s.visibility == "partner" and not acct["partner_bank"]):
        raise HTTPException(403, {"shared": False, "reason": "bank_does_not_share"})
    features = payee_features(s, upi_id, s.now)
    score, batch = mulehunter_score(s, upi_id, request.app.state.mulehunter_cache)
    return {
        "shared": True, "upi_id": upi_id, "bank": acct["bank"], "as_of": s.now.isoformat(),
        "features": features,
        "mulehunter": {"score": score, "as_of": batch.isoformat()},
    }
