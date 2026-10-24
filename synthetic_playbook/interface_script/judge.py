"""Reading the server's answers.

One payment: the server called it normal when its threat score is at or below `normal_max_score`.
One playbook: it got through when that share of its scam payments reached `breakthrough_share`.
A single miss is noise; most of them missed is a finding the blue team should see.

Honest payments are counted separately, as false alarms, so a playbook that only "wins" because the
server was lenient with everything is visible.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Verdict:
    playbook: str
    scorer: str
    normal_max_score: int
    breakthrough_share: float
    scam_judged: int = 0
    scam_missed: int = 0
    scam_caught: int = 0
    normal_judged: int = 0
    normal_flagged: int = 0          # honest payments the server did not call normal
    journeys: dict = field(default_factory=dict)   # journey_id -> {"judged": n, "missed": n}
    fail_open: int = 0               # the server answered T0 with no score (rule 3): not a miss
    errors: int = 0                  # no usable reply at all

    @property
    def miss_rate(self) -> float:
        return self.scam_missed / self.scam_judged if self.scam_judged else 0.0

    @property
    def false_alarm_rate(self) -> float:
        return self.normal_flagged / self.normal_judged if self.normal_judged else 0.0

    @property
    def breakthrough(self) -> bool:
        """Enough scam payments called normal, on enough evidence to not be a fluke."""
        return self.scam_judged > 0 and self.miss_rate >= self.breakthrough_share

    @property
    def journeys_fully_missed(self) -> int:
        return sum(1 for j in self.journeys.values() if j["judged"] and j["missed"] == j["judged"])

    def add(self, label: dict, reply: dict, status: int) -> dict:
        """Score one reply; returns the row written to results.csv."""
        reply = reply or {}
        threat = reply.get("threat") or {}
        score = threat.get("score")
        ok = status == 200 and score is not None
        # Fail open (rule 3): the check did not finish in time, so the server answered T0 with no
        # score. The playbook was never judged, so this counts as neither caught nor missed.
        failed_open = status == 200 and score is None and reply.get("fail_open")
        row = {**{k: v for k, v in label.items() if k != "judge"},
               "judged": label["judge"], "status": status,
               "threat_score": score, "threat_level": threat.get("level"),
               "fraud_type": threat.get("fraud_type"), "tier": reply.get("tier"),
               "fail_open": bool(failed_open),
               "reasons": "|".join(reply.get("reasons") or []),
               "called_normal": (score <= self.normal_max_score) if ok else None}
        if not label["judge"]:
            return row
        if not ok:
            self.fail_open += 1 if failed_open else 0
            self.errors += 0 if failed_open else 1
            return row
        called_normal = score <= self.normal_max_score
        if label["is_scam"]:
            self.scam_judged += 1
            j = self.journeys.setdefault(label["journey_id"], {"judged": 0, "missed": 0})
            j["judged"] += 1
            if called_normal:
                self.scam_missed += 1
                j["missed"] += 1
            else:
                self.scam_caught += 1
        else:
            self.normal_judged += 1
            if not called_normal:
                self.normal_flagged += 1
        return row

    def summary(self) -> dict:
        return {"playbook": self.playbook, "scorer": self.scorer,
                "normal_max_score": self.normal_max_score, "breakthrough_share": self.breakthrough_share,
                "scam_payments_judged": self.scam_judged, "scam_called_normal": self.scam_missed,
                "scam_detected": self.scam_caught, "miss_rate": round(self.miss_rate, 4),
                "journeys": len(self.journeys), "journeys_fully_missed": self.journeys_fully_missed,
                "normal_payments_judged": self.normal_judged, "normal_flagged": self.normal_flagged,
                "false_alarm_rate": round(self.false_alarm_rate, 4),
                "fail_open": self.fail_open, "errors": self.errors, "breakthrough": self.breakthrough}

    def text(self) -> str:
        s = self.summary()
        head = ("BREAKTHROUGH: the server called most of this playbook normal"
                if self.breakthrough else "No breakthrough: the server caught enough of this playbook")
        return "\n".join([
            f"{head}",
            f"  playbook              {s['playbook']}",
            f"  scorer                {s['scorer']}",
            f"  a payment is 'normal' at threat score <= {s['normal_max_score']}",
            f"  breakthrough needs    {s['breakthrough_share']:.0%} of scam payments called normal",
            "",
            f"  scam payments judged  {s['scam_payments_judged']}",
            f"    called normal       {s['scam_called_normal']}  ({self.miss_rate:.0%})",
            f"    detected            {s['scam_detected']}",
            f"  journeys              {s['journeys']} ({s['journeys_fully_missed']} missed at every step)",
            "",
            f"  honest payments       {s['normal_payments_judged']}",
            f"    flagged             {s['normal_flagged']}  ({self.false_alarm_rate:.1%} false alarms)",
            f"  fail-open (no score)  {s['fail_open']}   (rule 3: the check did not finish in time)",
            f"  failed requests       {s['errors']}",
        ])
