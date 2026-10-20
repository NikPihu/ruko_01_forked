"""Mock DoT Financial Fraud Risk Indicator: a risk level per Indian mobile number.

Built only from reports that have reached the lists (NCRP / 1930 complaints, Chakshu), weighted
by source and recency, refreshed once a day. Blind spots kept on purpose: report lag, fresh SIMs
have no history, and foreign numbers are outside DoT's numbering so are never rated.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/dot", tags=["DoT FRI (mock)"])

SOURCE_WEIGHT = {"1930": 1.0, "ncrp": 1.0, "chakshu": 0.5}
HALF_LIFE_DAYS = 30
LEVELS = ((3.0, "VERY_HIGH"), (1.5, "HIGH"), (0.5, "MEDIUM"))


def fri_level(s, mobile: str) -> dict:
    batch = s.last_batch()
    if not mobile.startswith("+91"):
        return {"mobile": mobile, "risk": "NONE", "reason": "not_an_indian_number", "as_of": batch.isoformat()}
    score = 0.0
    for r in s.reports_listed(mobile, batch):
        age_days = (batch - r["filed_at"]).total_seconds() / 86400
        score += SOURCE_WEIGHT.get(r["source"], 0.5) * 0.5 ** (age_days / HALF_LIFE_DAYS)
    risk = next((level for cut, level in LEVELS if score >= cut), "NONE")
    return {"mobile": mobile, "risk": risk, "as_of": batch.isoformat()}


@router.get("/fri/{mobile}")
def fri(mobile: str, request: Request) -> dict:
    return fri_level(request.app.state.store, mobile.strip())
