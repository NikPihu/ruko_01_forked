"""Mock I4C Suspect Registry: identifiers (UPI IDs, mobile numbers) named in cybercrime reports.

An identifier appears only once a report has been processed (listed_at), and false reports get
in too -- so a hit alone is evidence, not proof.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/i4c", tags=["I4C Suspect Registry (mock)"])


@router.get("/registry")
def registry(request: Request, upi_id: Optional[str] = None, mobile: Optional[str] = None) -> dict:
    if bool(upi_id) == bool(mobile):
        raise HTTPException(400, "pass exactly one of upi_id or mobile")
    s = request.app.state.store
    ident = upi_id.strip().lower() if upi_id else mobile.strip()
    hits = s.reports_listed(ident, s.now)
    return {
        "identifier": ident, "listed": bool(hits),
        "report_count": len({r["report_id"] for r in hits}),
        "first_listed_on": min(r["listed_at"] for r in hits).date().isoformat() if hits else None,
        "as_of": s.now.isoformat(),
    }
