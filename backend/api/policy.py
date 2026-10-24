"""Policy engine: scorer output + features -> tier, message, pause. All numbers come from YAML.

Rules, in order:
  1. A family is lit when its score >= family_threshold.
  2. Fewer than corroboration_min_families lit -> T0.
  3. Walk tiers T4 -> T1; first match wins (T4 also needs an intel hit).
  3b. A playbook two analysts approved (blue team, `approved_by` in the playbooks file) raises the
     tier to approved_playbooks.min_tier when its own conditions span min_condition_families
     families (rule 5: the evidence is still two independent families, checked by people).
  4. Amount caps (small payments are never interrupted).
  5. Trusted payee -> T0, unless an override holds (intel hit, or the journey reached S3 control).
  6. Alert budget: too many interruptions in 30 days -> drop to T1 unless p_scam is very high.
     Never applied while a journey is under way (S3 control, S4/S5 paying after contact), or
     when a family named in never_applies_with_families is lit (the payee itself looks risky).
  7. Message key = tier + playbook, or the generic key for the tier.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import yaml

TIER_ORDER = ("T0", "T1", "T2", "T3", "T4")
INTERRUPTIVE = {"T2", "T3", "T4"}


@dataclass
class Decision:
    tier: str
    message_key: str | None
    pause_minutes: int
    lit_families: list[str]
    intel_hit: bool
    applied: list[str] = field(default_factory=list)   # which rules changed the tier, for evidence


def intel_hit(f: dict) -> bool:
    return bool(f["payee_registry_listed"] or f["caller_registry_listed"]
                or f["payee_fri_level"] == 3 or f["caller_fri_level"] == 3)


class Policy:
    def __init__(self, path: str | Path = Path(__file__).with_name("policy.yaml")):
        self.cfg = yaml.safe_load(Path(path).read_text())
        self.version = self.cfg["version"]
        self._alerts: dict[str, list[datetime]] = {}

    def reset(self) -> None:
        self._alerts.clear()

    def decide(self, s: dict, f: dict, stage: str, control_seen: bool, user_id: str,
               now: datetime) -> Decision:
        c = self.cfg
        lit = sorted(k for k, v in s["family_scores"].items() if v >= c["family_threshold"])
        hit = intel_hit(f)
        applied: list[str] = []

        tier = "T0"
        if len(lit) >= c["corroboration_min_families"]:
            for name in ("T4", "T3", "T2", "T1"):
                rule = c["tiers"][name]
                if (s["p_scam"] >= rule["min_p"] and len(lit) >= rule["min_families"]
                        and (hit or not rule.get("requires_intel_hit"))):
                    tier = name
                    break
        elif s["p_scam"] >= c["tiers"]["T1"]["min_p"]:
            applied.append("corroboration_gate")

        ap, fams = c.get("approved_playbooks"), s.get("playbook_families")
        if ap and fams is not None and len(fams) >= ap["min_condition_families"] and _rank(tier) < _rank(ap["min_tier"]):
            tier = ap["min_tier"]
            applied.append("approved_playbook")

        for cap in c["amount_caps"]:
            if f["amount_inr"] < cap["below"] and _rank(tier) > _rank(cap["max_tier"]):
                tier = cap["max_tier"]
                applied.append(f"amount_cap_{cap['below']}")

        if f["trusted_payee"] and tier != "T0":
            overrides = c["trusted_payee"]["overridden_by"]
            if not (("intel_hit" in overrides and hit) or ("stage_ge_S3" in overrides and control_seen)):
                tier = "T0"
                applied.append("trusted_payee")

        budget = c["alert_budget"]
        recent = [t for t in self._alerts.get(user_id, []) if t > now - timedelta(days=30)]
        in_journey = stage in budget["never_applies_in_stages"] or (
            control_seen and "S3" in budget["never_applies_in_stages"])
        risky_payee = any(fam in lit for fam in budget.get("never_applies_with_families", []))
        if (tier in INTERRUPTIVE and not in_journey and not risky_payee and len(recent) >= budget["max_interruptive_per_30d"]
                and s["p_scam"] < budget["bypass_if_p_ge"]):
            tier = budget["drop_to"]
            applied.append("alert_budget")
        if tier in INTERRUPTIVE:
            self._alerts.setdefault(user_id, []).append(now)

        mk = c["message_keys"]
        key = None
        if tier != "T0":
            key = f"{tier.lower()}_{s['playbook']}" if s["playbook"] and tier in mk["playbook_tiers"] else mk[tier]
        return Decision(tier, key, c["pause_minutes"][tier], lit, hit, applied)


def _rank(tier: str) -> int:
    return TIER_ORDER.index(tier)
