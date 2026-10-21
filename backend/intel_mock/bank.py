"""Mock banks: each bank answers risk questions only about its own accounts.

Visibility modes reproduce how much a risk engine at a payment app can really see:
    none     no bank shares payee data (RUKO sees only NPCI's public fields)
    partner  only banks flagged partner share (default; today's reality for most apps)
    dpip     every bank shares, as if RBI's Digital Payments Intelligence Platform were live
"""
from __future__ import annotations

from datetime import timedelta

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


@router.get("/{code}/payee-flows/{upi_id}")
def payee_flows(code: str, upi_id: str, request: Request) -> dict:
    """Where this account forwards money: its top 10 outbound counterparties in the last 7 days.

    Same visibility as payee-risk. This is what a PSP could see through bank partnerships or RBI's
    DPIP, not the whole network.
    """
    s = request.app.state.store
    upi_id = upi_id.strip().lower()
    acct = s.account_at(upi_id, s.now)
    if acct is None or acct["bank_code"] != code:
        raise HTTPException(404, {"shared": False, "reason": "not_our_account"})
    if s.visibility == "none" or (s.visibility == "partner" and not acct["partner_bank"]):
        raise HTTPException(403, {"shared": False, "reason": "bank_does_not_share"})
    since = s.now - timedelta(days=7)
    ins = s.payments_in(upi_id, since, s.now)
    by_cp: dict[str, list] = {}
    for f in s.payments_out(upi_id, since, s.now):
        # Hold time: minutes since the latest money came in before this payment went out.
        prior = [i.ts for i in ins if i.ts <= f.ts]
        hold = (f.ts - prior[-1]).total_seconds() / 60 if prior else None
        by_cp.setdefault(f.counterparty, []).append((f.amount, hold))
    out = []
    for cp, rows in by_cp.items():
        holds = sorted(h for _, h in rows if h is not None)
        out.append({"upi_id": cp, "n": len(rows), "inr": round(sum(a for a, _ in rows), 2),
                    "median_hold_min": round(holds[len(holds) // 2], 1) if holds else None})
    out.sort(key=lambda r: -r["inr"])
    return {"shared": True, "upi_id": upi_id, "as_of": s.now.isoformat(), "outbound": out[:10]}
