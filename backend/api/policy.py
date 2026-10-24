"""Policy engine: scorer output + features -> tier, message, pause. All numbers come from YAML.

Rules, in order:
  1. A family is lit when its score >= family_threshold.
  2. Fewer than corroboration_min_families lit -> T0.
  3. Walk tiers T4 -> T1; first match wins (T4 also needs an intel hit).
  3b. A playbook two analysts approved (blue team, `approved_by` in the playbooks file) raises the
     tier to approved_playbooks.min_tier when its own conditions span min_condition_families
     families (rule 5: the evidence is still two independent families, checked by people).
  3c. RUKO's own cross-user evidence (evidence_overlay) raises to its min_tier when >= 2 families are lit.
  4. Amount caps (small payments are never interrupted).
  5. Trusted payee -> T0, unless an override holds (intel hit, or the journey reached S3 control).
  6. Approved-mule floor: a two-analyst-approved mule (rule 11) pauses even as the only lit family.
  7. Alert budget: too many interruptions in 30 days -> drop to T1 unless p_scam is very high.
     Never applied while a journey is under way (S3 control, S4/S5 paying after contact), when a
     family in never_applies_with_families is lit, or when an anchor-then-drain pattern is present.
  8. Message key = tier + playbook, or the generic key for the tier.
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

        # RUKO's own cross-user evidence (api/overlay.py) raises the tier only when it corroborates
        # with another lit family: on its own it never interrupts (rule 5).
        ov = c.get("evidence_overlay")
        if (ov and s.get("overlay") and len(lit) >= c["corroboration_min_families"]
                and _rank(tier) < _rank(ov["min_tier"])):
            tier = ov["min_tier"]
            applied.append("evidence_overlay")

        for cap in c["amount_caps"]:
            if f["amount_inr"] < cap["below"] and _rank(tier) > _rank(cap["max_tier"]):
                tier = cap["max_tier"]
                applied.append(f"amount_cap_{cap['below']}")

        if f["trusted_payee"] and tier != "T0":
            overrides = c["trusted_payee"]["overridden_by"]
            if not (("intel_hit" in overrides and hit) or ("stage_ge_S3" in overrides and control_seen)):
                tier = "T0"
                applied.append("trusted_payee")

        # A human-verified mule (rule 11) always pauses, even as the only lit family: it is not a
        # crowd-sourced registry entry that could be false, so corroboration is not needed (audit §2.6).
        floor = c.get("approved_mule_min_tier")
        if floor and f.get("payee_approved_suspect") and _rank(tier) < _rank(floor):
            tier = floor
            applied.append("approved_mule_floor")

        budget = c["alert_budget"]
        recent = [t for t in self._alerts.get(user_id, []) if t > now - timedelta(days=30)]
        in_journey = stage in budget["never_applies_in_stages"] or (
            control_seen and "S3" in budget["never_applies_in_stages"])
        risky_payee = any(fam in lit for fam in budget.get("never_applies_with_families", []))
        anchor = bool(f.get("payee_micro_anchor")) and budget.get("never_applies_with_anchor")
        if (tier in INTERRUPTIVE and not in_journey and not risky_payee and not anchor
                and len(recent) >= budget["max_interruptive_per_30d"]
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
