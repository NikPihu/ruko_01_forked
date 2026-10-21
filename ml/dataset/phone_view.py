"""What one phone would see and send at a Pay tap, rebuilt from the simulated world.

Mirrors the Android app so that training rows look like real requests:
- ContextSensor.readCall: VoIP calls never expose the number, so `caller_in_contacts` is null for
  them; outgoing SIM calls carry no number either; a call that ended in the last 30 minutes is
  still reported (kind, `ended_min_ago`).
- PhoneSignals: the caller's number is sent only for an incoming SIM call from a non-contact;
  `remote_access_active` needs the Android 15 screen-capture callback, otherwise it is null.
- SmsScan / bestLureTags: lures come from SMS only, last 72 h, best confidence per tag, >= 0.6.
- MoneyFlow.summarise: 72 h money summary; credits only when SMS checks are on.
- toRequestContext: a switched-off group is null; everything off means `context: null`.

Invented numbers (consent rates, pay-screen behaviour, ...) live in assumptions.yaml.
"""
from __future__ import annotations

import json
import math
import random
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from pathlib import Path
from statistics import median

import pandas as pd
import yaml

from schema.events import CallSignal, Context, DeviceSignal, LureSignal, MoneySignal

ASSUMPTIONS_PATH = Path(__file__).with_name("assumptions.yaml")
SCAM_TAGS = ("arrest_threat", "kyc", "task_job", "trading_tip", "refund")
MIN, HOUR, DAY = 60.0, 3600.0, 86400.0
INF = float("inf")
EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


def load_assumptions(path: str | Path = ASSUMPTIONS_PATH) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def keyed_rng(*key) -> random.Random:
    """Deterministic for a key, whatever order rows are processed in (string seeds are hashed
    with SHA-512, so PYTHONHASHSEED does not matter)."""
    return random.Random(":".join(map(str, key)))


def epoch_seconds(ts: pd.Series) -> list[float]:
    """Seconds since 1970 for a tz-aware timestamp column, whatever its stored resolution."""
    if len(ts) == 0:
        return []
    return (pd.to_datetime(ts) - EPOCH).dt.total_seconds().tolist()


def minutes(seconds: float) -> float:
    """ContextSensor.minutes: whole tenths of a minute, never negative."""
    return round(max(seconds, 0.0) / 6.0) / 10.0


def escalation_steps(amounts: list[float], factor: float) -> int:
    """MoneyFlow.escalationSteps: payments in a row, ending with the latest, each >= factor x the one before."""
    steps = 0
    for i in range(len(amounts) - 1, 0, -1):
        if amounts[i] >= factor * amounts[i - 1]:
            steps += 1
        else:
            break
    return steps


@dataclass(frozen=True)
class Traits:
    """Per user, fixed for the run, drawn independently of whether the user is scammed."""
    call_signals: bool
    app_checks: bool
    sms: bool
    android_15: bool
    pace: float  # personal speed on the pay screen; 1 is typical

    @property
    def any_shield(self) -> bool:
        return self.call_signals or self.app_checks or self.sms


@dataclass
class Call:
    start: float
    end: float  # INF while the call is still going at the end of the world
    kind: str  # sim | voip
    direction: str  # incoming | outgoing
    number: str
    in_contacts: bool


class Ledger:
    """Every user's own payments and credits, in time order (epoch seconds)."""

    def __init__(self, ledger: pd.DataFrame, user_upis: set[str], seed: int, parse_rate: float):
        self.outs: dict[str, tuple[list[float], list[str], list[float]]] = {}
        self.ins: dict[str, tuple[list[float], list[str], list[float], list[bool]]] = {}
        led = ledger.sort_values("ts", kind="stable")
        for t, frm, to, amt in zip(epoch_seconds(led.ts), led.from_upi.tolist(), led.to_upi.tolist(),
                                   led.amount.tolist()):
            if frm in user_upis:
                o = self.outs.setdefault(frm, ([], [], []))
                o[0].append(t), o[1].append(to), o[2].append(float(amt))
            if to in user_upis:
                i = self.ins.setdefault(to, ([], [], [], []))
                i[0].append(t), i[1].append(frm), i[2].append(float(amt))
        # Which bank alerts the phone's parser can read: fixed per credit, drawn per user in order.
        for upi, (ts, _, _, parsed) in self.ins.items():
            rng = keyed_rng(seed, "sms_parse", upi)
            parsed.extend(rng.random() < parse_rate for _ in ts)

    def outs_before(self, upi: str, t: float, since: float = -INF):
        ts, to, amt = self.outs.get(upi, ([], [], []))
        lo, hi = bisect_left(ts, since), bisect_left(ts, t)
        return ts[lo:hi], to[lo:hi], amt[lo:hi]

    def payees_before(self, upi: str, t: float) -> set[str]:
        ts, to, _ = self.outs.get(upi, ([], [], []))
        return set(to[:bisect_left(ts, t)])

    def ins_before(self, upi: str, t: float, since: float):
        ts, frm, amt, parsed = self.ins.get(upi, ([], [], [], []))
        lo, hi = bisect_left(ts, since), bisect_left(ts, t)
        return ts[lo:hi], frm[lo:hi], amt[lo:hi], parsed[lo:hi]


class PhoneView:
    """Rebuilds, for any user and moment, the `context` the phone would send and the private
    readings the on-device model uses."""

    def __init__(self, tables: dict[str, pd.DataFrame], assumptions: dict | None = None, seed: int = 0,
                 ledger: Ledger | None = None):
        self.a = assumptions or load_assumptions()
        self.p = self.a["phone"]
        self.seed = seed
        users = tables["users"]
        self.user_upi = dict(zip(users.user_id, users.upi_id))
        self.traits = {u: self._draw_traits(u, age) for u, age in zip(users.user_id, users.age_band)}
        acc = tables["accounts"]
        self.holder_type = dict(zip(acc.upi_id, acc.holder_type))
        self.ledger = ledger or Ledger(tables["ledger"], set(self.user_upi.values()), seed,
                                       self.p["bank_sms_parse_rate"])
        self._index_events(tables["context_events"])

    # ---------- setup ----------

    def _draw_traits(self, user_id: str, age_band: str) -> Traits:
        r = keyed_rng(self.seed, "traits", user_id)
        c, s = self.a["consent"], self.a["session"]
        return Traits(
            call_signals=r.random() < c["call_signals"], app_checks=r.random() < c["app_checks"],
            sms=r.random() < c["sms"], android_15=r.random() < self.a["android_15_share"],
            pace=r.lognormvariate(0, s["pace_sigma"]) * s["pace_by_age"].get(age_band, 1.0))

    def _index_events(self, ev: pd.DataFrame) -> None:
        self.calls: dict[str, list[Call]] = {}
        self.remote_installs: dict[str, list[float]] = {}
        self.sideloads: dict[str, list[float]] = {}
        self.accessibility: dict[str, list[float]] = {}
        self.remote_sessions: dict[str, list[float]] = {}
        self.lures: dict[str, list[tuple[float, str, float]]] = {}
        lure_types = {"sms_lure"} | ({"notification_lure"} if self.p["notification_lures_visible"] else set())
        open_calls: dict[tuple[str, str], list[Call]] = {}
        ev = ev.sort_values("ts", kind="stable")
        # ev["attrs"], not ev.attrs: DataFrame.attrs is pandas' own metadata dict.
        for t, uid, etype, raw in zip(epoch_seconds(ev["ts"]), ev["user_id"].tolist(), ev["event_type"].tolist(),
                                      ev["attrs"].tolist()):
            at = json.loads(raw)
            if etype == "call_started":
                c = Call(t, INF, at["call_kind"], at.get("direction", "incoming"), at["caller_number"],
                         bool(at["in_contacts"]))
                self.calls.setdefault(uid, []).append(c)
                open_calls.setdefault((uid, c.number), []).append(c)
            elif etype == "call_ended":
                pending = open_calls.get((uid, at["caller_number"]))
                if pending:
                    pending.pop(0).end = t
                else:  # started before the world: rebuild it from the duration
                    c = Call(t - at.get("duration_min", 0) * MIN, t, at["call_kind"],
                             at.get("direction", "incoming"), at["caller_number"], bool(at["in_contacts"]))
                    self.calls.setdefault(uid, []).append(c)
            elif etype == "app_installed":
                if at.get("is_remote_access"):
                    self.remote_installs.setdefault(uid, []).append(t)
                if at.get("sideloaded"):
                    self.sideloads.setdefault(uid, []).append(t)
            elif etype == "accessibility_enabled":
                self.accessibility.setdefault(uid, []).append(t)
            elif etype == "remote_session_notice":
                self.remote_sessions.setdefault(uid, []).append(t)
            elif etype in lure_types:
                self.lures.setdefault(uid, []).append((t, at["tag"], float(at["conf"])))
        for cs in self.calls.values():
            cs.sort(key=lambda c: c.start)
        self.call_starts = {u: [c.start for c in cs] for u, cs in self.calls.items()}
        for d in (self.remote_installs, self.sideloads, self.accessibility, self.remote_sessions):
            for v in d.values():
                v.sort()
        for v in self.lures.values():
            v.sort()
        self.lure_ts = {u: [x[0] for x in ls] for u, ls in self.lures.items()}

    # ---------- readings at a moment ----------

    def read_call(self, uid: str, t: float) -> tuple[CallSignal | None, dict | None]:
        """ContextSensor.readCall + CallReading.toCallSignal, for a user with call signals on."""
        if not self.traits[uid].call_signals:
            return None, None
        calls, starts = self.calls.get(uid, []), self.call_starts.get(uid, [])
        recent = calls[bisect_left(starts, t - 6 * HOUR):bisect_right(starts, t)]  # calls last < 6 h
        active = [c for c in recent if c.start <= t < c.end]
        sim = max((c for c in active if c.kind == "sim"), key=lambda c: c.start, default=None)
        voip = max((c for c in active if c.kind == "voip"), key=lambda c: c.start, default=None)
        known_out = self.p["outgoing_sim_number_known"]

        def number_of(c: Call) -> str | None:
            if c.kind != "sim":
                return None  # VoIP calls never expose the caller's number
            return c.number if c.direction == "incoming" or known_out else None

        if sim or voip:
            since = min(c.start for c in (sim, voip) if c)
            kind, direction = ("sim", sim.direction) if sim else ("voip", None)
            number = number_of(sim) if sim else None
            in_contacts = sim.in_contacts if number else None
            started, ended, active_flag = minutes(t - since), None, True
        else:
            last = max((c for c in recent if c.end <= t), key=lambda c: c.end, default=None)
            if last is None or t - last.end > self.p["call_memory_min"] * MIN:
                return CallSignal(active=False), {"active": False, "kind": None, "direction": None,
                                                  "in_contacts": None, "started_min_ago": None,
                                                  "ended_min_ago": None, "foreign": None}
            kind = last.kind
            direction = last.direction if kind == "sim" else None
            number = number_of(last)
            in_contacts = last.in_contacts if number else None
            started, ended, active_flag = None, minutes(t - last.end), False
        sent_number = number if kind == "sim" and direction == "incoming" and in_contacts is False else None
        sig = CallSignal(active=active_flag, kind=kind, direction=direction, caller_number=sent_number,
                         caller_in_contacts=in_contacts, started_min_ago=started, ended_min_ago=ended)
        raw = {"active": active_flag, "kind": kind, "direction": direction, "in_contacts": in_contacts,
               "started_min_ago": started, "ended_min_ago": ended,
               "foreign": None if number is None else not number.startswith("+91")}
        return sig, raw

    def read_device(self, uid: str, t: float) -> tuple[DeviceSignal | None, dict | None]:
        """ContextSensor.readDevice + DeviceReading.toDeviceSignal, for a user with app checks on."""
        tr = self.traits[uid]
        if not tr.app_checks:
            return None, None
        installs = self.remote_installs.get(uid, [])
        n = bisect_right(installs, t)
        installed = n > 0
        installed_min_ago = minutes(t - installs[n - 1]) if installed else None
        accessibility = bisect_right(self.accessibility.get(uid, []), t) > 0
        side = self.sideloads.get(uid, [])
        sideloaded = bisect_right(side, t) > bisect_right(side, t - DAY)
        if tr.android_15:
            sessions = self.remote_sessions.get(uid, [])
            dur = self.p["remote_session_minutes"] * MIN
            screen = bisect_right(sessions, t) > bisect_left(sessions, t - dur)
        else:
            screen = None
        active = True if screen is True and installed else False if screen is False else None
        sig = DeviceSignal(remote_access_active=active, remote_app_installed_min_ago=installed_min_ago,
                           untrusted_accessibility=accessibility, sideloaded_last_24h=sideloaded)
        raw = {"remote_installed": installed, "remote_min_ago": installed_min_ago, "screen_recorded": screen,
               "accessibility": accessibility, "sideloaded_24h": sideloaded}
        return sig, raw

    def read_lures(self, uid: str, t: float) -> tuple[list[LureSignal], list[tuple[str, float, float]] | None]:
        """SmsScan + bestLureTags. Returns (what is sent, every scam-tag hit for the on-device model)."""
        if not self.traits[uid].sms:
            return [], None
        ts = self.lure_ts.get(uid, [])
        window = self.lures.get(uid, [])[bisect_left(ts, t - self.p["lure_window_h"] * HOUR):bisect_right(ts, t)]
        hits = [(tag, conf, minutes(t - lt)) for lt, tag, conf in window if tag in SCAM_TAGS]
        best: dict[str, tuple[str, float, float]] = {}
        for h in hits:
            if h[1] >= self.p["lure_send_threshold"] and (h[0] not in best or h[1] > best[h[0]][1]):
                best[h[0]] = h
        sent = [LureSignal(tag=tag, conf=round(conf, 2), min_ago=round(ago, 1))
                for tag, conf, ago in sorted(best.values(), key=lambda h: -h[1])]
        return sent, hits

    def read_money(self, uid: str, t: float) -> tuple[MoneySignal | None, dict | None]:
        """MoneyFlow.summarise over this app's payments and (with SMS checks on) bank credit alerts."""
        tr = self.traits[uid]
        if not tr.any_shield:
            return None, None
        upi = self.user_upi[uid]
        since = t - self.p["money_window_h"] * HOUR
        o_ts, o_to, o_amt = self.ledger.outs_before(upi, t, since)
        paid_before = self.ledger.payees_before(upi, since)
        paid = paid_before | set(o_to)
        new_payees = len({p for p in o_to if p not in paid_before})
        raw = {"debits": len(o_amt), "debits_inr": sum(o_amt), "new_payees": new_payees,
               "escalation_steps": escalation_steps(o_amt, self.p["escalation_factor"]),
               "last_debit_inr": o_amt[-1] if o_amt else None,
               "bait_credits": None, "bait_inr": None, "credits_inr": None, "bait_30d": None}
        if tr.sms:
            i_ts, i_from, i_amt, parsed = self.ledger.ins_before(upi, t, since)
            seen = [(f, a) for f, a, ok in zip(i_from, i_amt, parsed) if ok]
            bait = [a for f, a in seen if a <= self.p["bait_max_inr"] and f not in paid]
            raw.update(bait_credits=len(bait), bait_inr=sum(bait), credits_inr=sum(a for _, a in seen))
            # 30-day view for the on-device episode features (the phone keeps 30 days encrypted).
            m_ts, m_from, m_amt, m_ok = self.ledger.ins_before(upi, t, t - 30 * DAY)
            paid_30 = self.ledger.payees_before(upi, t)
            raw["bait_30d"] = sum(1 for f, a, ok in zip(m_from, m_amt, m_ok)
                                  if ok and a <= self.p["bait_max_inr"] and f not in paid_30)
        sig = MoneySignal(
            bait_credits=raw["bait_credits"], credits_inr=raw["credits_inr"], debits=raw["debits"],
            debits_inr=raw["debits_inr"], new_payees=new_payees, escalation_steps=raw["escalation_steps"],
            last_debit_inr=raw["last_debit_inr"])
        return sig, raw

    def context_at(self, uid: str, t: float) -> tuple[Context | None, dict]:
        """The request's `context` (PhoneSignals.toRequestContext) and the raw readings."""
        call, call_raw = self.read_call(uid, t)
        device, device_raw = self.read_device(uid, t)
        lures, lure_hits = self.read_lures(uid, t)
        money, money_raw = self.read_money(uid, t)
        raw = {"call": call_raw, "device": device_raw, "lure_hits": lure_hits, "money": money_raw}
        if call is None and device is None and not lures and money is None:
            return None, raw
        return Context(call=call, device=device, lures=lures, money=money), raw

    # ---------- per payment draws ----------

    def payer_says(self, rng: random.Random, entry: str, amount: float, is_scam: bool,
                   playbook: str | None, payee_upi: str) -> str | None:
        ps = self.a["payer_says"]
        if entry != "typed" or amount < ps["ask_from_inr"] or rng.random() < ps["skip_rate"]:
            return None
        if is_scam:
            table = ps["scam"].get(playbook or "", ps["scam"]["default"])
        else:
            table = ps["normal"]["merchant" if self.holder_type.get(payee_upi) == "merchant" else "person"]
        answers, weights = zip(*table.items())
        return rng.choices(answers, weights=weights)[0]

    def session(self, rng: random.Random, uid: str, entry: str, is_scam: bool, playbook: str | None,
                first_time: bool) -> dict:
        """Pay-screen behaviour for one attempt, measured inside the app."""
        s = self.a["session"]
        coached = is_scam and rng.random() < s["coached_rate"].get(playbook or "", s["coached_rate"]["default"])
        kind = "coached" if coached else "normal"
        speed = "coached" if coached else ("new_payee" if first_time else "normal")
        secs = rng.lognormvariate(math.log(s["seconds_median"][speed] * self.traits[uid].pace), s["seconds_sigma"])
        return {
            "seconds": round(secs, 1),
            "pasted": entry == "typed" and rng.random() < s["pasted_upi_rate"][kind],
            "edits": _poisson(rng, s["amount_edits_mean"][kind]),
            "backgrounded": rng.random() < s["backgrounded_rate"][kind],
            "cancelled_10m": int(rng.random() < s["cancelled_10m_rate"][kind]),
            "coached": coached,  # ground truth, for evaluation only; never a feature
        }

    # ---------- own history (all UPI apps: this app + bank SMS) ----------

    def own_history(self, uid: str, t: float, days: int = 90) -> dict:
        upi = self.user_upi[uid]
        ts, _, amt = self.ledger.outs_before(upi, t, t - days * DAY)
        return {"ts": ts, "amounts": amt, "payees": self.ledger.payees_before(upi, t),
                "p95": _quantile(amt, 0.95) if amt else None, "max": max(amt) if amt else None,
                "median": median(amt) if amt else None}


def _quantile(xs: list[float], q: float) -> float:
    s = sorted(xs)
    k = (len(s) - 1) * q
    lo = math.floor(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _poisson(rng: random.Random, mean: float) -> int:
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1
