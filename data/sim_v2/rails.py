"""The rails: the only way agents touch the world. Each call writes the record a real system keeps.

    pay()        UPI switch  -> ledger row
    call()       telecom     -> call_started + call_ended events on the user's phone
    lure()       SMS / app notification -> sms_lure / notification_lure event
    remote_app() phone OS    -> app_installed (remote access) + remote_session_notice
    sideload()   phone OS    -> app_installed (sideloaded) + accessibility_enabled
    decide()     any agent   -> decisions row (who, why, p, draw, outcome); returns its id

Raw truth is written here. What a given phone may *see* (consents, Android version) is applied
later by ml/dataset/phone_view.py, as for data/sim.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta

from sim_v2.core.rng import R
from sim_v2.core.tables import attrs
from sim_v2.world import FOREIGN_CODES, REMOTE_PKGS, World


def in_window(w: World, ts: datetime) -> bool:
    return w.start - timedelta(days=1) <= ts <= w.end


def pay(w: World, ts: datetime, frm: str, to: str, amount: float, entry: str, flow: str, *,
        journey_id=None, is_scam=False, stage=None, scenario=None, cause=None) -> bool:
    if not in_window(w, ts):
        return False
    w.ledger.add(ts, frm, to, float(round(amount)), entry, flow, journey_id, bool(is_scam), stage, scenario, cause)
    return True


def event(w: World, ts: datetime, user_id: str, kind: str, a: dict, *, journey_id=None, stage=None,
          scenario=None, cause=None) -> None:
    if in_window(w, ts):
        w.events.add(ts, user_id, kind, attrs(a), journey_id, journey_id is not None, stage, scenario, cause)


def call(w: World, ts: datetime, user_id: str, number: str, minutes: float, *, in_contacts: bool, kind: str = "sim",
         direction: str = "incoming", **tags) -> datetime:
    a = {"caller_number": number, "call_kind": kind, "in_contacts": in_contacts, "direction": direction,
         "country_code": number[:-10]}
    if kind == "voip":
        a["voip_caller_is_number"] = True
    event(w, ts, user_id, "call_started", a, **tags)
    end = ts + timedelta(minutes=minutes)
    event(w, end, user_id, "call_ended", {**a, "duration_min": round(minutes, 1)}, **tags)
    return end


def lure(w: World, ts: datetime, user_id: str, tag: str, conf: float, *, notification=False, has_link=False, **tags):
    a = {"tag": tag, "conf": round(conf, 2)}
    if has_link:
        a["has_link"] = True
    event(w, ts, user_id, "notification_lure" if notification else "sms_lure", a, **tags)


def remote_app(w: World, r: R, ts: datetime, user_id: str, **tags) -> None:
    pkg = r.choice(REMOTE_PKGS)
    event(w, ts, user_id, "app_installed", {"pkg": pkg, "is_remote_access": True, "sideloaded": False}, **tags)
    event(w, ts + timedelta(minutes=r.uniform(1, 5)), user_id, "remote_session_notice", {"pkg": pkg}, **tags)


def sideload(w: World, r: R, ts: datetime, user_id: str, **tags) -> None:
    pkg = f"com.kyc.update{r.integer(0, 999)}"
    event(w, ts, user_id, "app_installed", {"pkg": pkg, "is_remote_access": False, "sideloaded": True}, **tags)
    event(w, ts + timedelta(minutes=r.uniform(1, 5)), user_id, "accessibility_enabled", {"pkg": pkg}, **tags)


def number(w: World, r: R, foreign: bool = False) -> str:
    return w.mobile(r, r.choice(FOREIGN_CODES)) if foreign else w.mobile(r)


def decide(w: World, r: R, *, decision_id: str, ts: datetime, agent: str, kind: str, inputs: dict,
           journey_id=None, step=None, step_no: int | None = None, p: float | None = None,
           options: dict | None = None, forced: str | None = None) -> str:
    """Log one decision. Either a yes/no with probability p, or a pick among `options` weights.
    Returns the outcome. `forced` is for scripted scenarios (logged as such, draw = None)."""
    if forced is not None:
        outcome, u = forced, None
    elif options is not None:
        u = r.random()
        acc, outcome = 0.0, None
        total = sum(options.values())
        for k, v in options.items():
            acc += v / total
            if u < acc:
                outcome = k
                break
        outcome = outcome or list(options)[-1]
    else:
        u = r.random()
        outcome = "yes" if u < p else "no"
    w.decisions.add(decision_id, ts, agent, kind, journey_id, step, step_no, json.dumps(inputs, sort_keys=True, default=str),
                    None if p is None else float(p), u, outcome)
    return outcome


def logistic(x: float) -> float:
    return 1 / (1 + math.exp(-x))
