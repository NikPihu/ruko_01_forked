"""What the phone sends at the moment of Pay, and what RUKO answers.

Only derived flags leave the phone (no SMS text, audio, contacts). Any missing field means
"unknown", never "safe". `context: null` means the user opted out of sharing phone signals.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

# Bump on any shape change, and re-export contracts/ (python -m schema.export).
CONTRACT_VERSION = "c2-0.4"

Tier =Literal["T0", "T1", "T2", "T3", "T4"]
ReasonCode = Literal[
    "R1_live_unknown_call", "R2_remote_control", "R3_mule_like_payee", "R4_unusual_amount",
    "R5_lure_message", "R6_new_payee_typed", "R7_tranche_pattern", "R8_intel_hit",
    "R9_story_mismatch", "R10_bait_then_pay", "R11_ring_link", "ruko_unavailable",
]
LureTag = Literal["arrest_threat", "kyc", "task_job", "trading_tip", "refund", "normal"]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CallSignal(_M):
    active: Optional[bool] = None
    kind: Optional[Literal["sim", "voip"]] = None
    direction: Optional[Literal["incoming", "outgoing"]] = None
    caller_number: Optional[str] = None          # used only for FRI / registry lookups
    caller_in_contacts: Optional[bool] = None
    started_min_ago: Optional[float] = Field(None, ge=0)
    ended_min_ago: Optional[float] = Field(None, ge=0)  # for a call that just finished


class DeviceSignal(_M):
    remote_access_active: Optional[bool] = None
    remote_app_installed_min_ago: Optional[float] = Field(None, ge=0)
    untrusted_accessibility: Optional[bool] = None
    sideloaded_last_24h: Optional[bool] = None


class LureSignal(_M):
    tag: LureTag
    conf: float = Field(ge=0, le=1)
    min_ago: float = Field(ge=0)


class EpisodeSignal(_M):
    """Task-scam episode kept on the phone across payees for up to 30 days (c2-0.3).

    Built by the phone's background watcher from bank SMS alerts and this app's payments, with
    the rules in contracts/episode_rules.json. Counts only; bait fields are null when SMS can't be read.
    """
    state: Literal["none", "watching", "active", "dismissed"]
    age_days: Optional[float] = Field(None, ge=0)          # since first bait credit
    bait_credits: Optional[int] = Field(None, ge=0)        # null when SMS can't be read
    bait_inr: Optional[float] = Field(None, ge=0)
    outs: Optional[int] = Field(None, ge=0)                # after first bait, any app, excl. this payment
    outs_inr: Optional[float] = Field(None, ge=0)
    new_payees: Optional[int] = Field(None, ge=0)
    escalation_steps: Optional[int] = Field(None, ge=0)
    last_out_inr: Optional[float] = Field(None, gt=0)
    out_to_in_ratio: Optional[float] = Field(None, ge=0)
    payee_seen_in_episode: Optional[bool] = None           # this payee already paid in this episode
    rules_version: Optional[str] = None                    # e.g. "episode-0.1"


class Context(_M):
    call: Optional[CallSignal] = None
    device: Optional[DeviceSignal] = None
    lures: list[LureSignal] = Field(default_factory=list)
    episode: Optional[EpisodeSignal] = None  # c2-0.3 (the c2-0.2 `money` group was removed in c2-0.4)


class DecideRequest(_M):
    request_id: str
    user_id: str
    payee_upi_id: str
    amount_inr: float = Field(gt=0)
    entry_method: Literal["typed", "qr", "contact", "collect"]
    # Answer to "Who are you paying?" (asked for first-time payees over a threshold).
    payer_says: Optional[Literal["government", "company", "family", "shop", "investment", "other"]] = None
    ts: AwareDatetime
    context: Optional[Context] = None


class DecideResponse(_M):
    request_id: str
    tier: Tier
    reasons: list[ReasonCode]
    message_key: Optional[str] = None
    pause_minutes: int = 0
    playbook: Optional[str] = None
    stage: Optional[str] = None
    evidence_id: Optional[str] = None
    fail_open: bool = False
    contract_version: str = CONTRACT_VERSION
    # Never p_scam: the user sees reasons in words, never a score.


# ---------- Episode events: phone -> server when the episode changes state (c2-0.4) ----------

EpisodeTrigger = Literal["watching", "active", "out_payment", "bait", "dismissed", "closed"]


class EpisodeAccount(_M):
    upi_id: str                                   # plain: needed for intel lookups and the graph
    role: Literal["bait_sender", "payee"]
    n: int = Field(ge=1)                          # times seen in this episode
    inr: float = Field(ge=0)                      # total with this account in this episode
    first_seen_min_ago: float = Field(ge=0)
    via: Optional[Literal["this_app", "other_app"]] = None   # payees only; other_app = debit SMS
    step: Optional[int] = Field(None, ge=1)       # payees only: position in the escalation run


class EpisodeEvent(_M):
    """POST /v1/episode. Sent only on state changes, and only with "Share suspicious accounts" on."""
    event_id: str                                 # UUID; the server ignores repeats (safe to retry)
    episode_id: str                               # UUID, stable for the whole episode
    user_id: str
    ts: AwareDatetime
    trigger: EpisodeTrigger
    rules_version: str                            # "episode-0.2"
    summary: EpisodeSignal                        # same object as context.episode
    accounts: list[EpisodeAccount] = Field(default_factory=list, max_length=10)


class EpisodeEventResponse(_M):
    event_id: str
    episode_risk: Literal["unknown", "low", "elevated", "high"]   # words, never a score
    reasons: list[ReasonCode]
    message_key: Optional[str] = None             # e.g. "episode_task_scam_confirmed"
    case_id: Optional[str] = None                 # set when an analyst case was opened
    contract_version: str = CONTRACT_VERSION
