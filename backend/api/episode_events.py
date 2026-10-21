"""POST /v1/episode: the phone's watcher reports a state change with the accounts involved (c2-0.4).

1. Ignore repeats by event_id (the phone retries).
2. Look up each account with the IntelAdapter (NPCI, bank payee features, registry, FRI). Anything
   missing is unknown, not clean.
3. Hand the episode's edges to the payment graph, when there is one (§9).
4. Store per-user episode evidence for the next /v1/decide.
5. Write an evidence record and open an analyst case when the risk is high.
6. Reply with episode_risk in words, reasons and a message key. Never a score.

episode_risk uses the same two-family rule as payments:
    high      episode ACTIVE (lure family) and payee-family evidence on at least one account
    elevated  only one of the two
    low       neither
    unknown   every lookup timed out or failed
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from api.intel import IntelAdapter, IntelResult
from features.build import FRI_LEVEL
from evidence.store import EvidenceStore, pseudonym
from graph.store import user_node
from schema.events import EpisodeEvent, EpisodeEventResponse

# Episode events are off the payment path, so lookups may take longer than a decide's 150 ms.
LOOKUP_BUDGET_S = 1.0
UNREACHED = {"timeout", "error", "skipped"}
STOP_TRIGGERS = {"dismissed", "closed"}


@dataclass
class AccountCheck:
    upi_id: str
    role: str
    mule_like: Optional[bool] = None      # None: the payee's bank did not answer or share
    intel_hit: Optional[bool] = None
    ring: dict = field(default_factory=dict)   # graph signals (crowd, money loop), filled by §9
    reached: bool = False
    verified_merchant: Optional[bool] = None
    holder_type: Optional[str] = None

    @property
    def payee_evidence(self) -> bool:
        return bool(self.mule_like or self.intel_hit or self.ring.get("crowd") or self.ring.get("money_loop"))


def check_account(upi: str, role: str, res: IntelResult) -> AccountCheck:
    """Payee-family evidence for one account, with the same thresholds as api/rule_scorer.py."""
    bank = (res.bank or {}).get("features") or {}
    u6, rep, pt, age = (bank.get("uniq_payers_6h"), bank.get("repeat_payer_ratio_30d"),
                        bank.get("pass_through_24h"), bank.get("account_age_days"))
    mule_like = None
    if bank:
        mh = ((res.bank or {}).get("mulehunter") or {}).get("score") or 0
        mule_like = bool((u6 is not None and rep is not None and u6 >= 10 and rep < 0.3)
                         or (pt is not None and age is not None and pt >= 0.8 and age < 30) or mh >= 0.5)
    listed = (res.payee_registry or {}).get("listed")
    fri = FRI_LEVEL.get((res.payee_fri or {}).get("risk"), 0)
    intel_hit = None if res.status.get("payee_registry") in UNREACHED else bool(listed or fri >= 2)
    reached = any(v not in UNREACHED for v in res.status.values())
    npci = res.npci or {}
    return AccountCheck(upi, role, mule_like, intel_hit, reached=reached,
                        verified_merchant=npci.get("verified_merchant"), holder_type=npci.get("holder_type"))


class EpisodeService:
    def __init__(self, intel: IntelAdapter, evidence: EvidenceStore, graph=None):
        self.intel, self.evidence, self.graph = intel, evidence, graph
        self.replies: dict[str, EpisodeEventResponse] = {}
        # user_id -> latest evidence, read by /v1/decide
        self.by_user: dict[str, dict] = {}
        self.cases: list[dict] = []

    def reset(self) -> None:
        self.replies.clear()
        self.by_user.clear()
        self.cases.clear()

    async def handle(self, ev: EpisodeEvent, now: datetime) -> EpisodeEventResponse:
        if ev.event_id in self.replies:
            return self.replies[ev.event_id]
        if ev.trigger in STOP_TRIGGERS:
            self.by_user.pop(ev.user_id, None)
            if self.graph is not None:
                self.graph.add_episode(ev, now)
            return self._reply(ev, EpisodeEventResponse(event_id=ev.event_id, episode_risk="low", reasons=[]))

        results = await asyncio.gather(*(self.intel.lookup(a.upi_id, budget_s=LOOKUP_BUDGET_S) for a in ev.accounts))
        checks = [check_account(a.upi_id.strip().lower(), a.role, r) for a, r in zip(ev.accounts, results)]
        if self.graph is not None and self.graph.add_episode(ev, now):
            # Where each account forwards money, when its bank shares (for the money loop).
            flows = await asyncio.gather(*(self.intel.flows(c.upi_id) for c in checks))
            for c, f in zip(checks, flows):
                self.graph.add_bank_flows(c.upi_id, f)
                self.graph.mark(c.upi_id, flagged=bool(c.mule_like or c.intel_hit) or None,
                                listed=c.intel_hit or None, role=c.role,
                                verified_merchant=c.verified_merchant, holder_type=c.holder_type)
            for c in checks:
                c.ring = self.graph.account_signals(c.upi_id, now)

        lure = ev.summary.state == "active"
        payee = any(c.payee_evidence for c in checks if c.role == "payee") or any(
            c.intel_hit or c.ring.get("crowd") for c in checks if c.role == "bait_sender")
        if checks and not any(c.reached for c in checks) and not payee:
            risk = "unknown"
        else:
            risk = "high" if lure and payee else "elevated" if lure or payee else "low"

        reasons: list[str] = []
        if lure:
            reasons.append("R10_bait_then_pay")
        if any(c.mule_like for c in checks):
            reasons.append("R3_mule_like_payee")
        if any(c.intel_hit for c in checks):
            reasons.append("R8_intel_hit")
        if any(c.ring.get("money_loop") or c.ring.get("crowd") for c in checks):
            reasons.append("R11_ring_link")

        flagged = sorted(c.upi_id for c in checks if c.payee_evidence)
        self.by_user[ev.user_id] = {"episode_id": ev.episode_id, "risk": risk, "flagged": set(flagged),
                                    "ts": now.isoformat()}
        evidence_id = f"e_{uuid.uuid4().hex[:12]}"
        case_id = None
        if risk == "high":
            if self.graph is not None:
                for upi in flagged:
                    self.graph.mark(upi, flagged=True)
                self.graph.protect([c.upi_id for c in checks] + [user_node(ev.user_id)])
            case_id = f"c_{uuid.uuid4().hex[:12]}"
            self.cases.append({"case_id": case_id, "opened_at": now.isoformat(), "user_hash": pseudonym(ev.user_id),
                               "episode_id": ev.episode_id, "evidence_id": evidence_id, "accounts": flagged,
                               "reasons": reasons, "loop_paths": [c.ring.get("loop_path") for c in checks if c.ring.get("loop_path")]})
        self.evidence.write({
            "id": evidence_id, "ts": now.isoformat(), "user_hash": pseudonym(ev.user_id),
            "payee_hash": None, "caller_hash": None, "tier": f"episode_{risk}", "p_scam": None,
            "reasons": reasons, "playbook": "task_job" if lure else None,
            "family_scores": {"lit": [f for f, on in (("L", lure), ("P", payee)) if on]},
            "features": {"trigger": ev.trigger, "summary": ev.summary.model_dump(),
                         "accounts": [{"hash": pseudonym(c.upi_id), "role": c.role, "mule_like": c.mule_like,
                                       "intel_hit": c.intel_hit, "ring": c.ring} for c in checks]},
            "intel_status": {c.upi_id[:3] + "…": c.reached for c in checks},
            "stage_path": [], "model_version": ev.rules_version, "policy_version": "episode-risk-0.1",
        })
        msg = {"high": "episode_task_scam_confirmed", "elevated": "episode_task_scam_possible"}.get(risk)
        return self._reply(ev, EpisodeEventResponse(event_id=ev.event_id, episode_risk=risk, reasons=reasons,
                                                    message_key=msg, case_id=case_id))

    def _reply(self, ev: EpisodeEvent, r: EpisodeEventResponse) -> EpisodeEventResponse:
        self.replies[ev.event_id] = r
        return r
