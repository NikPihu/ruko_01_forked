"""Alert feedback (c2-0.8): what users do on alert screens, and the alert-health numbers it gives.

One row per action in the transaction database. "I know this person" adds the payee to the user's
trusted list only when RUKO had no reason to doubt it: no list hit on the payee or caller, no
sign that someone else controls the phone (stage S3 or a remote-control app), and a payee whose
own evidence (the payee family) was not lit: a user can vouch for a person, not for a mule account. Coached victims tap
"I know them" too, so it can never switch off the strongest warnings (same rule as policy.yaml
`trusted_payee.overridden_by`).
"""
from __future__ import annotations

import statistics
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from typing import Callable

from api.policy import intel_hit
from evidence.store import pseudonym
from schema.events import Feedback, FeedbackResponse
from store.db import TxnStore

INTERRUPTIVE = ("T2", "T3", "T4")


class FeedbackService:
    def __init__(self, store: TxnStore, trusted: dict[str, set[str]], evidence, per_user_per_day: int = 30,
                 persist: Callable = lambda fn, *a: fn(*a)):
        self.store, self.trusted, self.evidence = store, trusted, evidence
        self.per_user_per_day = per_user_per_day
        self.persist = persist
        self._today: dict[tuple[str, str], int] = defaultdict(int)
        self._seen: dict[str, FeedbackResponse] = {}

    def reset(self) -> None:
        self._today.clear()
        self._seen.clear()

    def handle(self, fb: Feedback, now: datetime) -> FeedbackResponse:
        if fb.feedback_id in self._seen:                       # the phone retried: same answer
            return self._seen[fb.feedback_id]
        payment = self.store.payment(fb.request_id)
        mine = payment is not None and payment["user_hash"] == pseudonym(fb.user_id)
        key = (fb.user_id, now.date().isoformat())
        if not mine or self._today[key] >= self.per_user_per_day:
            return FeedbackResponse(feedback_id=fb.feedback_id, recorded=False)
        self._today[key] += 1

        accepted, message_key = None, None
        if fb.action == "i_know_them":
            details = self.store.details(fb.request_id) or {}
            f = details.get("features") or {}
            control = bool(f.get("remote_control")) or any(st == "S3" for st, _ in details.get("stage_path") or [])
            # The user can vouch for a person, not for an account that behaves like a mule.
            mule_like = "P" in (details.get("lit_families") or [])
            # Unknown is not safe: without the decision's details there is nothing to vouch for.
            accepted = bool(f) and not (intel_hit(_with_defaults(f)) or control or mule_like)
            if accepted:
                self.trusted.setdefault(fb.user_id, set()).add(payment["payee_upi"])
                self.persist(self.store.record_trusted, fb.user_id, payment["payee_upi"], "feedback", now)
            else:
                message_key = "know_them_not_accepted"

        self.persist(self.store.record_feedback, {
            "feedback_id": fb.feedback_id, "payment_id": fb.request_id, "user_id": fb.user_id,
            "action": fb.action, "why": fb.why, "dwell_ms": fb.dwell_ms, "trusted_accepted": accepted,
            "ts": fb.ts})
        self.persist(self.evidence.write, {
            "id": f"e_{uuid.uuid4().hex[:12]}", "ts": now.isoformat(), "user_hash": pseudonym(fb.user_id),
            "payee_hash": pseudonym(payment["payee_upi"]), "caller_hash": None, "tier": "feedback", "p_scam": None,
            "reasons": [], "playbook": None, "family_scores": {},
            "features": {"action": fb.action, "why": fb.why, "dwell_ms": fb.dwell_ms, "request_id": fb.request_id,
                         "trusted_accepted": accepted},
            "intel_status": {}, "stage_path": [], "model_version": None, "policy_version": None})
        resp = FeedbackResponse(feedback_id=fb.feedback_id, recorded=True, trusted_accepted=accepted,
                                message_key=message_key)
        self._seen[fb.feedback_id] = resp
        return resp


def _with_defaults(f: dict) -> dict:
    keys = ("payee_registry_listed", "caller_registry_listed", "payee_fri_level", "caller_fri_level")
    return {k: f.get(k) for k in keys}


def alert_health(store: TxnStore) -> dict:
    """Aggregates for the console (numbers about alerts, never one user's score)."""
    payments = store.transactions(limit=1000)
    checks = len(payments)
    by_tier = defaultdict(list)
    for p in payments:
        by_tier[p["tier"]].append(p)
    out: dict = {"checks": checks, "tiers": {}}
    actions: Counter = Counter()
    know = Counter()
    for tier in ("T1", "T2", "T3", "T4"):
        rows = by_tier.get(tier, [])
        dwell, tier_actions = [], Counter()
        for p in rows:
            for f in store.feedback_for(p["payment_id"]):
                tier_actions[f["action"]] += 1
                actions[f["action"]] += 1
                if f["dwell_ms"] is not None:
                    dwell.append(f["dwell_ms"])
                if f["action"] == "i_know_them":
                    know["accepted" if f["trusted_accepted"] else "refused"] += 1
        n = len(rows)
        out["tiers"][tier] = {
            "shown": n,
            "completed_share": round(sum(p["status"] == "completed" for p in rows) / n, 3) if n else None,
            "cancelled_share": round(sum(p["status"] == "cancelled" for p in rows) / n, 3) if n else None,
            "median_dwell_ms": statistics.median(dwell) if dwell else None,
            "actions": dict(tier_actions),
        }
    interrupted = sum(len(by_tier.get(t, [])) for t in INTERRUPTIVE)
    out["interruptions_per_1000_checks"] = round(1000 * interrupted / checks, 2) if checks else None
    out["actions"] = dict(actions)
    out["i_know_them"] = dict(know)
    return out
