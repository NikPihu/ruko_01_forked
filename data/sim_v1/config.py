"""Knobs for sim_v1. Each number says where it comes from: NPCI (real, India), Xente (real, shape
only), AML sets (SAML-D / AMLworld typologies), or 'assumption' (ours, to be checked)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
HERE = Path(__file__).resolve().parent
P2P_TXN_CAP = 100_000  # UPI per-transaction limit for P2P

# Xente legit hour-of-day curve (real). Used as the shape of when people pay.
XENTE_HOURS = [0.0153, 0.0071, 0.0030, 0.0017, 0.0018, 0.0030, 0.0074, 0.0244, 0.0435, 0.0557, 0.0599,
               0.0590, 0.0569, 0.0627, 0.0651, 0.0549, 0.0545, 0.0542, 0.0657, 0.0763, 0.0762, 0.0662,
               0.0537, 0.0316]

# NPCI bank volume shares, Sep 2026 (real), for the handles we model.
HANDLES = {  # handle: (bank, app, share)
    "ybl": ("Yes Bank", "PhonePe", 0.41), "oksbi": ("State Bank of India", "Google Pay", 0.12),
    "okaxis": ("Axis Bank", "Google Pay", 0.11), "okhdfcbank": ("HDFC Bank", "Google Pay", 0.07),
    "paytm": ("Paytm Payments Bank", "Paytm", 0.12), "okicici": ("ICICI Bank", "Google Pay", 0.05),
    "ibl": ("IndusInd Bank", "PhonePe", 0.04), "axl": ("Axis Bank", "PhonePe", 0.08),
}

# persona: (share, median payments/day, P2M share, amount multiplier). Assumption, tuned so the
# population matches NPCI's P2M share and average tickets.
PERSONAS = {
    "student":    (0.20, 0.9, 0.70, 0.6),
    "salaried":   (0.30, 1.0, 0.62, 1.2),
    "homemaker":  (0.15, 0.6, 0.72, 0.9),
    "senior":     (0.10, 0.3, 0.55, 1.1),
    "gig_worker": (0.15, 1.2, 0.60, 0.8),
    "shopkeeper": (0.10, 1.4, 0.45, 1.4),
}

PLAYBOOKS = {  # name: weight. Shares are an assumption based on I4C / news reporting mix.
    "digital_arrest": 0.20, "task_job": 0.22, "trading_group": 0.16,
    "fake_kyc_apk": 0.14, "refund_qr": 0.12, "fake_customer_care": 0.16,
}


@dataclass(frozen=True)
class V1Config:
    seed: int = 7
    n_users: int = 3000
    n_days: int = 60
    end: datetime = datetime(2026, 11, 7, tzinfo=IST)
    world: str = "train"  # train: many scams to learn from; eval: realistic prevalence

    # Spread of activity between users: Xente log daily-rate sigma is 1.47 (one service only);
    # 1.1 for an all-purpose UPI app is an assumption.
    activity_sigma: float = 1.1
    # Amount mixtures (log-normal bulk + log-normal tail), fitted to NPCI by calibrate.py.
    p2m_bulk_median: float = 150.0
    p2m_bulk_sigma: float = 0.95
    p2m_tail_median: float = 2500.0
    p2m_tail_sigma: float = 0.9
    p2m_tail_weight: float = 0.08
    p2p_bulk_median: float = 250.0
    p2p_bulk_sigma: float = 1.0
    p2p_tail_median: float = 6000.0
    p2p_tail_sigma: float = 0.9
    p2p_tail_weight: float = 0.3
    p2m_shift: float = 0.0  # added to every persona's P2M share; fitted with the amounts

    new_merchant_p: float = 0.08    # payment to a merchant the user never paid before (assumption)
    new_person_p: float = 0.05      # payment to a person never paid before (assumption)
    new_account_share: float = 0.10  # honest accounts younger than 90 days (assumption; fixes the age leak)

    # Hard negatives (legit but scam-looking). Assumptions.
    rent_share: float = 0.25          # users paying monthly rent by UPI
    big_new_payee_rate: float = 0.03  # per user per 30 days: large first-time P2P (deposit, worker, tuition)

    # Phone context on legit payments (base rates; assumptions). None when consent is off (rule 1).
    consent_share: float = 0.6
    legit_on_call: float = 0.04
    legit_remote_app: float = 0.015
    legit_lure_72h: float = 0.08

    # Scams
    victim_rate_train: float = 0.05
    victim_rate_eval: float = 0.004
    mule_kinds: dict = field(default_factory=lambda: {"fresh": 0.4, "aged_rented": 0.4, "merchant_disguised": 0.2})
    # Mule fan-in from victims outside our users, per mule per week (SAML-D / AMLworld: about 3 senders).
    mule_external_per_week: float = 3.0
    mule_pass_through: float = 0.85  # AMLworld median pass-through is lower (0.58); SAML-D higher

    @property
    def start(self) -> datetime:
        return self.end - timedelta(days=self.n_days)

    @property
    def victim_rate(self) -> float:
        return self.victim_rate_train if self.world == "train" else self.victim_rate_eval


def load(**overrides) -> V1Config:
    """Defaults, then calibrated.json if calibrate.py has written one, then explicit overrides."""
    cfg = V1Config()
    cal = HERE / "calibrated.json"
    if cal.exists():
        cfg = replace(cfg, **json.loads(cal.read_text())["params"])
    return replace(cfg, **overrides)
