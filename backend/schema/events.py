"""What the phone sends at the moment of Pay, and what RUKO answers.

Only derived flags leave the phone (no SMS text, audio, contacts). Any missing field means
"unknown", never "safe". `context: null` means the user opted out of sharing phone signals.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

# Bump on any shape change, and re-export contracts/ (python -m schema.export).
CONTRACT_VERSION = "c2-0.14"

Tier =Literal["T0", "T1", "T2", "T3", "T4"]
ReasonCode = Literal[
    "R1_live_unknown_call", "R2_remote_control", "R3_mule_like_payee", "R4_unusual_amount",
    "R5_lure_message", "R6_new_payee_typed", "R7_tranche_pattern", "R8_intel_hit",
    "R9_story_mismatch", "R10_bait_then_pay", "R11_ring_link", "R12_coached_session",
    "R13_scam_campaign",  # c2-0.13: the payee or caller is being pushed in scam messages to many people
    "ruko_unavailable",
]
# c2-0.14: other_scam (a scam outside the five kinds) and unclear (no class reached the 0.6 bar: never
# treated as normal, rule 1), from the lure-0.2 classifier.
LureTag = Literal["arrest_threat", "kyc", "task_job", "trading_tip", "refund", "other_scam", "unclear", "normal"]
# The known scam workflows (playbooks); the engine's and the phone's fraud class use the same names.
FraudType = Literal["digital_arrest", "fake_customer_care", "fake_kyc_apk", "trading_group", "task_job", "refund_qr"]
ThreatLevel = Literal["none", "low", "medium", "high", "critical"]


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
    speaker_on: Optional[bool] = None            # c2-0.5: call audio on the loudspeaker at Pay
    # c2-0.10: a VoIP call with the camera in use by another app at Pay (a video call, e.g. a fake
    # "officer" watching the payment). The phone sees only that the camera is busy, never images.
    video: Optional[bool] = None


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


class SessionSignal(_M):
    """How the user behaved on the Pay screen of THIS payment (c2-0.5).

    Measured inside the app, from opening Pay to tapping Pay. Only counts and rounded durations:
    never the keys typed, never which other app was open. Field meanings: contracts/README.md.
    """
    amount_digits: Optional[int] = Field(None, ge=0)              # digit key presses in the amount box
    amount_median_gap_s: Optional[float] = Field(None, ge=0)      # typical pause between those digits
    amount_max_gap_s: Optional[float] = Field(None, ge=0)         # longest pause between them
    amount_gap_vs_usual: Optional[float] = Field(None, ge=0)      # median gap / this user's usual; null until 3 past payments
    amount_edits: Optional[int] = Field(None, ge=0)               # deletions in the amount box
    payee_pasted: Optional[bool] = None                           # the UPI ID arrived in one paste
    pasted_within_s_of_return: Optional[float] = Field(None, ge=0)  # paste this soon after coming back to the app
    app_switches: Optional[int] = Field(None, ge=0)               # times the app went to the background
    away_s: Optional[float] = Field(None, ge=0)                   # total time away
    pay_screen_s: Optional[float] = Field(None, ge=0)             # opening Pay -> tapping Pay
    abandoned_flows_30m: Optional[int] = Field(None, ge=0)        # payments started and left unpaid, last 30 min


# c2-0.14: the scam steps vocabulary (contracts/steps.json), shared by the phone's verdict, the engine,
# the playbooks and the blue team.
STEPS_JSON = Path(__file__).resolve().parents[2] / "contracts" / "steps.json"
STEP_IDS = tuple(s["id"] for s in json.loads(STEPS_JSON.read_text(encoding="utf-8"))["steps"])
StepId = Literal[STEP_IDS]  # type: ignore[valid-type]


class StepSeen(_M):
    """One step the phone saw in this journey (c2-0.14), with how long ago when it has a time."""
    step: StepId
    min_ago: Optional[float] = Field(None, ge=0)


class DeviceVerdict(_M):
    """The phone's own model on what only the phone can see (c2-0.8; ml/model/device, DeviceModel.kt).

    Calls, apps, SMS (through the lure model), the episode, the Pay screen and the payment history
    are read on the phone and stay there; only this verdict leaves it. Family scores are 0..1,
    rounded to 2 decimals, and each counts only in its own family on the server (rule 5).
    """
    model_version: str                                   # e.g. "device-0.1"
    fraud_class: Optional[FraudType] = None              # the scam the phone's signals point to, if any
    level: Literal["low", "medium", "high"]              # the phone's own threat level
    c: Optional[float] = Field(None, ge=0, le=1)         # calls and remote control; null = not measured
    l: Optional[float] = Field(None, ge=0, le=1)         # lure messages and the task-scam episode
    b: Optional[float] = Field(None, ge=0, le=1)         # own spending and the Pay screen
    reasons: list[ReasonCode] = Field(default_factory=list, max_length=3)
    # c2-0.14: the steps the phone saw (features/steps.py phone_steps) and the ones it could not measure
    # (a switch off, no permission); a phone step in neither list was measured and not seen.
    steps_seen: Optional[list[StepSeen]] = Field(None, max_length=len(STEP_IDS))
    steps_unmeasured: Optional[list[StepId]] = Field(None, max_length=len(STEP_IDS))  # type: ignore[valid-type]


class Context(_M):
    call: Optional[CallSignal] = None
    device: Optional[DeviceSignal] = None
    lures: list[LureSignal] = Field(default_factory=list)
    episode: Optional[EpisodeSignal] = None  # c2-0.3 (the c2-0.2 `money` group was removed in c2-0.4)
    session: Optional[SessionSignal] = None  # c2-0.5
    # c2-0.7: the payee's UPI ID, or the mobile number it was paid by, is a saved contact on the
    # phone. Only this yes/no leaves the phone, never names or numbers. null = contacts not readable.
    payee_in_contacts: Optional[bool] = None
    device_verdict: Optional[DeviceVerdict] = None  # c2-0.8: null when the phone's model did not run


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


class Threat(_M):
    """The server's threat analysis of this payment (c2-0.8): every family, the phone's verdict,
    payee intel (bank features, MuleHunter, FRI, I4C registry) and the payment graph."""
    score: int = Field(ge=0, le=100)                     # 0..100 (100 x the scorer's p_scam, rounded)
    level: ThreatLevel                                    # T0 none, T1 low, T2 medium, T3 high, T4 critical
    fraud_type: Optional[FraudType] = None               # the known scam it matches, if any
    families: list[Literal["C", "L", "P", "B"]] = Field(default_factory=list)  # families that agree


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
    # c2-0.8: the threat analysis, shown to the user (a team decision that replaced "never a score").
    # null when RUKO failed open.
    threat: Optional[Threat] = None


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


# ---------- Payment outcome: phone -> server after the PIN or Cancel (c2-0.6) ----------

PaymentStatus = Literal["completed", "cancelled"]


class PaymentOutcome(_M):
    """POST /v1/payment/outcome. What happened to a payment after its check. The payment id is the
    /v1/decide `request_id`. Payee and amount are repeated so the payment is recorded even when the
    check never reached the server (timeout, fail open). Safe to retry."""
    request_id: str                               # the payment id: same UUID as its /v1/decide request
    user_id: str
    payee_upi_id: str                             # plain, as in /v1/decide
    amount_inr: float = Field(gt=0)
    status: PaymentStatus                         # completed = PIN entered; cancelled = user left without paying
    ts: AwareDatetime                             # when it was completed or cancelled


class PaymentOutcomeResponse(_M):
    request_id: str
    status: PaymentStatus                         # the status the server holds (the first final one wins)
    recorded: bool                                # False: a repeat, a conflicting status, or not accepted
    contract_version: str = CONTRACT_VERSION


# ---------- Alert feedback: what the user did on an alert screen (c2-0.9) ----------

FeedbackAction = Literal[
    "tip_seen",              # T1 tip shown on the way to the PIN
    "slid_to_pay",           # T2: read the card, then slid to pay
    "cancelled_from_alert",  # left the payment from any alert screen
    "waited",                # T3: chose to wait out the pause
    "pay_after_pause",       # T3: paid once the pause ended
    "called_trusted", "messaged_trusted", "called_1930",
    "i_know_them",           # "I know this person" (needs `why`)
]
KnowWhy = Literal["family", "friend", "shop", "landlord", "employer", "other"]


class Feedback(_M):
    """POST /v1/feedback. One action on one alert. Safe to retry (same feedback_id)."""
    feedback_id: str                              # UUID
    request_id: str                               # the payment id: the /v1/decide request_id
    user_id: str
    action: FeedbackAction
    why: Optional[KnowWhy] = None                 # only with i_know_them
    dwell_ms: Optional[int] = Field(None, ge=0)   # alert shown -> this action
    ts: AwareDatetime


class FeedbackResponse(_M):
    feedback_id: str
    recorded: bool                                # False: unknown payment, someone else's, or over the daily limit
    # i_know_them only: False when RUKO still recommends waiting (a list hit, or someone controls the phone).
    trusted_accepted: Optional[bool] = None
    message_key: Optional[str] = None             # e.g. "know_them_not_accepted"
    contract_version: str = CONTRACT_VERSION


# ---------- Watch events: early warnings before any payment (c2-0.9) ----------

WatchKind = Literal[
    "lure_seen",             # a scam-script message (SMS or notification); tag only, never text
    "remote_access_on",      # screen sharing / remote control started
    "long_unknown_call",     # a call with an unknown or non-contact caller passed N minutes
    "sideload",              # an app was installed from outside the store
]


class Handle(_M):
    """A money handle from a scam message (c2-0.13): what the crew wants paid, opened or called.
    The UPI ID is plain (payees are plain, rule 7); a link host or call-back number is a salted
    SHA-256 pseudonym "sha256:<hex>" (graph/campaigns.py, contracts/examples/handle_vectors.json).
    Never the message text (rule 2)."""
    kind: Literal["upi", "link", "phone"]
    value: str = Field(min_length=3, max_length=100)


class WatchEvent(_M):
    """POST /v1/watch. Sent only when a threshold is crossed (never on a timer), only with
    "Early warnings" on. Moves the user's scam stage forward before a payment."""
    event_id: str                                 # UUID; repeats are ignored
    user_id: str
    kind: WatchKind
    ts: AwareDatetime                             # when it happened on the phone
    lure_tag: Optional[LureTag] = None            # lure_seen only
    lure_conf: Optional[float] = Field(None, ge=0, le=1)
    source: Optional[Literal["sms", "notification"]] = None   # lure_seen only
    ai_written: Optional[bool] = None             # lure_seen only (c2-0.10): the message looked AI-written
    handles: Optional[list[Handle]] = Field(None, max_length=10)  # lure_seen only (c2-0.13): money handles
    call_kind: Optional[Literal["sim", "voip"]] = None        # long_unknown_call only
    call_minutes: Optional[float] = Field(None, ge=0)         # long_unknown_call only


class WatchEventResponse(_M):
    event_id: str
    recorded: bool
    stage: Optional[str] = None                   # the user's stage after this event (S0 to S3)
    contract_version: str = CONTRACT_VERSION


# ---------- Money received, read from a bank SMS on the phone (c2-0.11) ----------

class MoneyReceived(_M):
    """POST /v1/payment/received. A credit the phone's money watch read from a bank SMS alert: the
    amount, the sender's UPI ID and the time, never the SMS text (rule 2). Sent only with "Share money
    received" on (off by default, rule 7). Safe to retry: a repeated event_id is not recorded twice."""
    event_id: str                                 # UUID made on the phone, one per credit
    user_id: str                                  # the receiver (pseudonymised on the server)
    sender_upi_id: Optional[str] = None           # the UPI ID the alert named; null when it named none (rule 1)
    amount_inr: float = Field(gt=0)
    ts: AwareDatetime                             # when the bank SMS arrived
    source: Literal["bank_sms"] = "bank_sms"
    sender_name: Optional[str] = Field(None, max_length=80)  # c2-0.12: the account holder's name the bank gave


class MoneyReceivedResponse(_M):
    event_id: str
    recorded: bool                                # False for a repeated event_id
    contract_version: str = CONTRACT_VERSION


# ---------- The app's own payments, as the server recorded them (c2-0.9) ----------

class MyPayment(_M):
    """GET /v1/me/payments?user_id=. Plain words only: never a score (rule 4)."""
    payment_id: str
    payee_upi_id: str
    amount_inr: float
    ts: AwareDatetime
    tier: Tier
    reasons: list[ReasonCode]
    message_key: Optional[str] = None
    playbook: Optional[str] = None
    status: Literal["checked", "completed", "cancelled"]
    outcome_ts: Optional[AwareDatetime] = None


class MyPayments(_M):
    payments: list[MyPayment]
    contract_version: str = CONTRACT_VERSION
