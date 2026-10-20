"""Knobs for the synthetic UPI world. Every number here is a modelling assumption, not a fact."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

# UPI person-to-person cap per transaction (₹1 lakh).
P2P_TXN_CAP = 100_000


@dataclass(frozen=True)
class Handle:
    handle: str
    bank: str
    app: str
    # Invented: which banks run the mock MuleHunter / share payee data with RUKO.
    partner: bool


HANDLES: tuple[Handle, ...] = (
    Handle("oksbi", "State Bank of India", "Google Pay", True),
    Handle("okhdfcbank", "HDFC Bank", "Google Pay", True),
    Handle("okaxis", "Axis Bank", "Google Pay", True),
    Handle("okicici", "ICICI Bank", "Google Pay", False),
    Handle("ybl", "Yes Bank", "PhonePe", False),
    Handle("ibl", "IndusInd Bank", "PhonePe", False),
    Handle("axl", "Axis Bank", "PhonePe", True),
    Handle("paytm", "Paytm Payments Bank", "Paytm", False),
)


@dataclass(frozen=True)
class SimConfig:
    seed: int = 7
    n_users: int = 2000
    n_days: int = 30
    end: datetime = datetime(2026, 11, 7, 0, 0, tzinfo=IST)

    # Share of users who go through a scam journey inside the window.
    scam_rate: float = 0.01
    # Victims who ever report (SPEC assumption ~0.49).
    report_rate: float = 0.5
    # Days between the last scam payment and the victim filing a report.
    report_lag_days: tuple[float, float] = (0.0, 3.0)
    # Days between filing and the identifier showing up on lists (registry / FRI inputs).
    listing_lag_days: tuple[float, float] = (1.0, 4.0)
    # Share of honest accounts hit by a false report.
    false_entry_share: float = 0.01
    # Chance that another recipient of the same scam campaign reports the caller on Chakshu.
    chakshu_report_rate: float = 0.3
    # Outside victims paying each first-layer mule, per day (low, high); drawn once per mule.
    external_victims_per_day: tuple[float, float] = (0.5, 4.0)

    mule_kind_weights: dict[str, float] = field(default_factory=lambda: {
        "plain": 0.45, "merchant_disguised": 0.2, "warm_up": 0.2, "slow_forward": 0.15,
    })
    playbook_weights: dict[str, float] = field(default_factory=lambda: {
        "digital_arrest": 0.30, "trading_group": 0.15, "task_job": 0.15,
        "fake_kyc_apk": 0.15, "refund_qr": 0.12, "fake_customer_care": 0.13,
    })

    @property
    def start(self) -> datetime:
        return self.end - timedelta(days=self.n_days)

    @property
    def n_kirana(self) -> int:
        return max(12, self.n_users // 40)

    @property
    def n_mules(self) -> int:
        return max(6, self.n_users // 150)

    @property
    def n_cash_out(self) -> int:
        return max(4, self.n_mules // 2)

    @property
    def n_journeys(self) -> int:
        return max(1, round(self.n_users * self.scam_rate))
