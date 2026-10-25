"""Stage tracker: follows one user's possible scam journey for 72 hours.

S0 nothing · S1 contacted · S2 hooked · S3 under control · S4 paying · S5 paying again.
In-memory for now; the interface is small so a Redis version can replace it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from features.episode import effective_episode
from schema.events import DecideRequest

WINDOW = timedelta(hours=72)
CALL_MEMORY = timedelta(minutes=30)   # a call that ended this recently still counts as "on call"
CONTROL_AFTER_CONTACT = timedelta(hours=2)
# Shared with the phone's early warnings (rule 6): contracts/watch_rules.json.
WATCH_RULES = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "watch_rules.json").read_text(encoding="utf-8"))
LURE_MIN_CONF: float = WATCH_RULES["lure_min_conf"]
LONG_CALL_MIN: float = WATCH_RULES["long_call_min"]
# c2-0.15: an OTP that arrived during an unknown call counts for this long (account takeover in progress).
OTP_MEMORY = timedelta(minutes=WATCH_RULES.get("otp_recent_min", 120))
STAGES = ("S0", "S1", "S2", "S3", "S4", "S5")


@dataclass
class Attempt:
    ts: datetime
    payee: str
    amount: float
    new_payee: bool


@dataclass
class Session:
    contacts: list[datetime] = field(default_factory=list)
    control_ts: datetime | None = None
    lure_ts: datetime | None = None
    episode_hooked: bool = False   # the phone's task-scam episode is ACTIVE
    long_call: bool = False        # the phone reported a long call with an unknown caller (watch event)
    otp_ts: datetime | None = None # c2-0.15: an OTP arrived during a call with an unknown number (watch event)
    attempts: list[Attempt] = field(default_factory=list)
    recent_out: list[tuple[datetime, float]] = field(default_factory=list)  # new-payee payments, for 24h cumulative outflow
    stage_path: list[tuple[str, datetime]] = field(default_factory=list)


@dataclass
class TrackerState:
    """What the rest of the engine needs from the tracker for one decision."""
    stage: str
    stage_path: list[tuple[str, datetime]]
    on_call: bool | None
    attempts_72h: int          # earlier attempts to new payees in the window, not counting this one
    new_payee_sum_72h: float   # including this one
    outflow_24h: float         # payments to new/unknown payees in the last 24h, any entry method (incl. this one)
    payee_in_run: bool         # this payee is new, or one of those earlier new payees
    minutes_since_first_contact: float | None
    otp_on_call: bool | None = None  # c2-0.15: an OTP arrived during an unknown call within OTP_MEMORY; None = not reported


class StageTracker:
    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}

    def reset(self) -> None:
        self.sessions.clear()

    def update(self, req: DecideRequest, new_payee: bool) -> TrackerState:
        now = req.ts
        s = self.sessions.setdefault(req.user_id, Session())
        self._expire(s, now)
        ctx = req.context
        call = ctx.call if ctx else None
        dev = ctx.device if ctx else None

        on_call = None
        if call is not None:
            recent_end = call.ended_min_ago is not None and call.ended_min_ago <= CALL_MEMORY.total_seconds() / 60
            on_call = bool(call.active) or recent_end
            # A WhatsApp-type (VoIP) call never shows the number, so its contact status is null:
            # unknown is not safe (rule 1), so it counts as a possible contact like a stranger's call.
            unknown_caller = call.caller_in_contacts is False or (
                call.kind == "voip" and call.caller_in_contacts is None)
            if (call.active or recent_end) and unknown_caller:
                started = now - timedelta(minutes=call.started_min_ago or 0)
                if not any(abs((c - started).total_seconds()) < 60 for c in s.contacts):
                    s.contacts.append(started)
        if ctx:
            for lure in ctx.lures:
                if lure.tag != "normal" and lure.conf >= LURE_MIN_CONF:
                    ts = now - timedelta(minutes=lure.min_ago)
                    s.lure_ts = max(s.lure_ts or ts, ts)
        ep = effective_episode(ctx)
        if ep and ep["state"] in ("watching", "active"):
            # The first bait credit is first contact (S1); an active episode means hooked (S2).
            started = now - timedelta(days=ep["age_days"] or 0)
            s.lure_ts = min(s.lure_ts or started, started)
            s.episode_hooked = s.episode_hooked or ep["state"] == "active"
        if dev is not None:
            control_signal = dev.remote_access_active or dev.untrusted_accessibility or (
                dev.remote_app_installed_min_ago is not None and dev.remote_app_installed_min_ago <= 120)
            if control_signal:
                ago = dev.remote_app_installed_min_ago or 0
                s.control_ts = s.control_ts or now - timedelta(minutes=ago)

        earlier_new = [a for a in s.attempts if a.new_payee]
        if new_payee:
            s.attempts.append(Attempt(now, req.payee_upi_id, req.amount_inr, True))
        # Cumulative 24h outflow to new/unknown payees, across every entry method: salami-sliced
        # draining (many small QR/contact tranches) is caught even when no single payment looks
        # unusual. Payments to established payees (the bank's history) are excluded, so paying a
        # known landlord in instalments does not light this.
        s.recent_out = [(t, a) for t, a in s.recent_out if t > now - timedelta(hours=24)]
        if new_payee:
            s.recent_out.append((now, req.amount_inr))
        outflow_24h = sum(a for _, a in s.recent_out)
        stage = self._stage(s, call, new_payee, earlier_new)
        if not s.stage_path or s.stage_path[-1][0] != stage:
            s.stage_path.append((stage, now))
        first = min([*s.contacts, *([s.lure_ts] if s.lure_ts else [])], default=None)
        return TrackerState(
            stage=stage, stage_path=list(s.stage_path), on_call=on_call,
            attempts_72h=len(earlier_new),
            new_payee_sum_72h=sum(a.amount for a in s.attempts if a.new_payee),
            outflow_24h=outflow_24h,
            payee_in_run=new_payee or any(a.payee == req.payee_upi_id for a in earlier_new),
            minutes_since_first_contact=(now - first).total_seconds() / 60 if first else None,
            # True or unknown, never False: the phone reports only when it saw one, and only with
            # "Early warnings" on, so no report is not proof of no OTP (rule 1).
            otp_on_call=True if s.otp_ts is not None and timedelta(0) <= now - s.otp_ts <= OTP_MEMORY else None,
        )

    def observe(self, user_id: str, kind: str, ts: datetime, *, lure_conf: float | None = None,
                call_minutes: float | None = None) -> str:
        """A watch event from the phone before any payment (c2-0.8). Returns the stage it leads to."""
        s = self.sessions.setdefault(user_id, Session())
        self._expire(s, ts)
        if kind == "lure_seen" and (lure_conf is None or lure_conf >= LURE_MIN_CONF):
            s.lure_ts = max(s.lure_ts or ts, ts)
        elif kind in ("remote_access_on", "sideload"):
            s.control_ts = s.control_ts or ts
        elif kind == "long_unknown_call":
            started = ts - timedelta(minutes=call_minutes or 0)
            if not any(abs((c - started).total_seconds()) < 60 for c in s.contacts):
                s.contacts.append(started)
            s.long_call = True
        elif kind == "otp_during_call":
            # Someone on an unknown call is after a one-time code: that is contact and an attempt to
            # take control of an account (S3), whether or not a payment follows in RUKO.
            if not any(abs((c - ts).total_seconds()) < 60 for c in s.contacts):
                s.contacts.append(ts)
            s.otp_ts = max(s.otp_ts or ts, ts)
            s.control_ts = s.control_ts or ts
        stage = self._stage(s, None, False, [])
        if not s.stage_path or s.stage_path[-1][0] != stage:
            s.stage_path.append((stage, ts))
        return stage

    @staticmethod
    def _stage(s: Session, call, new_payee: bool, earlier_new: list[Attempt]) -> str:
        contacted = bool(s.contacts) or s.lure_ts is not None
        if not contacted and s.control_ts is None:
            return "S0"
        stage = "S1"
        unknown = call is not None and (call.caller_in_contacts is False or (
            call.caller_in_contacts is None and call.kind == "voip"))
        long_call = s.long_call or (unknown and (call.started_min_ago or 0) >= LONG_CALL_MIN)
        if len(s.contacts) >= 2 or (s.contacts and s.lure_ts) or long_call or s.episode_hooked:
            stage = "S2"
        first = min([*s.contacts, *([s.lure_ts] if s.lure_ts else [])], default=None)
        if s.control_ts and (first is None or s.control_ts - first <= CONTROL_AFTER_CONTACT):
            stage = "S3"
        if new_payee:
            stage = "S5" if earlier_new else "S4"
        return stage

    @staticmethod
    def _expire(s: Session, now: datetime) -> None:
        cutoff = now - WINDOW
        if s.otp_ts is not None and s.otp_ts <= cutoff:
            s.otp_ts = None
        s.contacts = [c for c in s.contacts if c > cutoff]
        s.long_call = s.long_call and bool(s.contacts)
        s.attempts = [a for a in s.attempts if a.ts > cutoff]
        if s.lure_ts and s.lure_ts <= cutoff:
            s.lure_ts = None
        if s.control_ts and s.control_ts <= cutoff:
            s.control_ts = None
        s.stage_path = [p for p in s.stage_path if p[1] > cutoff]
