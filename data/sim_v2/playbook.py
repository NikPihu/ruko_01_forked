"""Runs one scam journey from a playbook YAML (config/playbooks/*.yaml): the scam as a state machine.

The victim decides at every `ask` (and at steps with `decide`) with a logged formula:

    capacity = income x savings_months   (what the person can reach)
    score    = base[persona] + pressure + sunk_cost * min(1, paid_so_far / capacity)
               - doubt_per_refusal * refusals - big_ask * max(0, ask / capacity - 0.3)
    p_comply = 1 / (1 + exp(-score))
    comply with p_comply; otherwise delay (retry later, once) or refuse (journey ends)

Every term, p, the random draw and the outcome go to decisions.parquet; every payment and event
the step causes carries that decision's id in `cause_id`.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sim_v2 import rails
from sim_v2.agents.scammer import Crew
from sim_v2.core.rng import R, draw
from sim_v2.world import World


class Journey:
    def __init__(self, w: World, jid: str, user: dict, playbook: str, start: datetime, crew: Crew,
                 is_demo=False, forced_mule: str | None = None):
        self.w, self.jid, self.user, self.pb_name, self.crew = w, jid, user, playbook, crew
        self.pb = w.cfg.playbooks[playbook]
        self.r: R = w.r("journey", jid)
        self.t, self.start = start, start
        self.is_demo, self.forced_mule = is_demo, forced_mule
        self.variant = self.r.weighted(self.pb["variants"]) if "variants" in self.pb else None
        # steps are numbered by their order in the YAML: 1, 2, 3 ...
        self.step_no = {s["id"]: i + 1 for i, s in enumerate(self.pb["steps"])}
        self.last_cause = None   # latest decision in this journey; events that follow it carry its id
        self.paid, self.payments, self.mules = 0.0, [], []
        self.prev_ask, self.refusals, self.n_dec, self.complied = None, 0, 0, 0
        self.caller, self.call_kind = None, None
        self.call_start = self.call_end = None
        self.outcome = "completed"
        self.last_activity = start

    # ---------- helpers ----------
    def did(self) -> str:
        self.n_dec += 1
        return f"D_{self.jid}_{self.n_dec:02d}"

    def tags(self, stage, cause=None) -> dict:
        return {"journey_id": self.jid, "stage": stage, "cause": cause}

    def victim(self, step: str, pressure: float, ask: float = 0.0) -> tuple[str, str]:
        w, v, u = self.w, self.w.cfg.a["victim"], self.user
        inc = max(u["income_month"], 1000)
        cap = inc * u["savings_months"]
        terms = {"base": v["base"][u["persona"]], "pressure": pressure,
                 "sunk": round(v["sunk_cost"] * min(1.0, self.paid / cap), 3),
                 "doubt": -v["doubt_per_refusal"] * self.refusals,
                 "big_ask": round(-v["big_ask"] * max(0.0, ask / cap - 0.3), 3)}
        p = rails.logistic(sum(terms.values()))
        delay = (1 - p) * v["delay_share"] if self.refusals < v["max_delays"] else 0.0
        did = self.did()
        out = rails.decide(w, self.r, decision_id=did, ts=self.t, agent=u["user_id"], kind="victim",
                           journey_id=self.jid, step=step, step_no=self.step_no.get(step), p=round(p, 4),
                           inputs={**terms, "ask_inr": round(ask), "capacity_inr": round(cap), "paid_so_far": round(self.paid)},
                           options={"comply": p, "delay": delay, "refuse": max(0.0, 1 - p - delay)},
                           forced="comply" if self.is_demo else None)
        self.last_cause = did
        return out, did

    def number(self, kind: str) -> str:
        if kind == "voip":
            foreign = [n for n, f in self.crew.numbers if f]
            return foreign[0] if foreign else self.crew.numbers[0][0]
        local = [n for n, f in self.crew.numbers if not f]
        return local[0] if local else self.crew.numbers[0][0]

    # ---------- step pieces ----------
    def events(self, step: dict, cause: str | None) -> None:
        w, r, uid, stage = self.w, self.r, self.user["user_id"], step.get("stage", "S1")
        for e in step.get("events", []):
            t = e["type"]
            if t == "call":
                kind = self.call_kind if e["kind"] == "same" and self.call_kind else r.weighted(e["kind"]) if isinstance(e["kind"], dict) else e["kind"]
                self.call_kind, self.caller = kind, self.number(kind)
                self.call_start = self.t
                self.call_end = rails.call(w, self.t, uid, self.caller, draw(r, e["minutes"]), in_contacts=False,
                                           kind=kind, direction=e.get("direction", "incoming"), **self.tags(stage, cause))
            elif t in ("sms_lure", "notification_lure"):
                tag = e["tag"][self.variant] if isinstance(e["tag"], dict) else e["tag"]
                rails.lure(w, self.t, uid, tag, draw(r, e["conf"]), notification=t == "notification_lure",
                           has_link=e.get("has_link", False), **self.tags(stage, cause))
            elif t == "remote_app":
                rails.remote_app(w, r, self.t, uid, **self.tags(stage, cause))
            elif t == "sideload_apk":
                rails.sideload(w, r, self.t, uid, **self.tags(stage, cause))
            self.t += timedelta(minutes=r.uniform(0.5, 3))

    def crew_pays(self, spec: dict, cause: str | None) -> None:
        r = self.r
        for k in range(int(draw(r, spec.get("repeat", 1)))):
            if k:
                self.t += timedelta(minutes=draw(r, spec.get("gap_min", [60, 360])))
            amount = max(1, round(draw(r, spec["amount"], prev=self.prev_ask, total=self.paid)))
            rails.pay(self.w, self.t, r.choice(self.crew.cash_out), self.user["upi_id"], amount, "typed", "scam_bait",
                      journey_id=self.jid, cause=cause)

    def ask(self, step: dict, spec: dict) -> bool:
        """One ask: the victim decides; on comply the amount is paid (maybe in tranches). False = journey over."""
        w, r, v = self.w, self.r, self.w.cfg.a["victim"]
        amount = max(100, draw(r, spec["amount"], prev=self.prev_ask, total=self.paid))
        pressure = spec.get("pressure", 0.5)
        if spec.get("during_call") and self.call_end and self.t > self.call_end - timedelta(minutes=5):
            # coached payment: the scammer is still on the line, so it happens before the call ends
            span = (self.call_end - self.call_start).total_seconds()
            self.t = self.call_start + timedelta(seconds=span * r.uniform(0.4, 0.8))
        while True:
            out, did = self.victim(step["id"], pressure, amount)
            if out == "comply":
                self.complied += 1
                break
            if out == "delay":
                self.refusals += 1
                self.t += timedelta(hours=r.uniform(2, 24))
                pressure += 0.3
                continue
            self.refusals += 1
            self.outcome = f"refused_at:{step['id']}"
            return False
        self.prev_ask = amount
        cap = w.cfg.get("amounts.p2p_cap")
        n = max(int(draw(r, spec.get("split", 1))), -(-int(amount) // cap))
        cuts = sorted(r.random() for _ in range(n - 1))
        parts = [b - a for a, b in zip([0.0, *cuts], [*cuts, 1.0])]
        for part in parts:
            a = max(100.0, amount * part)
            a = round(a, -2) if r.chance(spec.get("round", 0.5)) else round(a)
            entry = r.weighted(spec.get("entry", {"typed": 1.0}))
            slot = {"same": 0, "second": 1, "rotate": len(self.payments)}[spec.get("mule", "same")]
            mule = self.forced_mule or self.crew.mule(slot, self.t)
            stage = "S4" if not self.payments else "S5"
            if rails.pay(w, self.t, self.user["upi_id"], mule, min(a, cap), entry, "scam", journey_id=self.jid,
                         is_scam=True, stage=stage, cause=did):
                self.payments.append((self.t, mule, min(a, cap)))
                self.paid += min(a, cap)
                if mule not in self.mules:
                    self.mules.append(mule)
                kind = w.accounts[mule]["mule_kind"]
                cash = w.demo_cash_out if self.forced_mule else r.choice(self.crew.cash_out)
                w.mule_inflows.append((self.t, mule, min(a, cap), f"{self.jid}:{len(self.payments)}", self.jid, cash, kind))
            self.t += timedelta(minutes=r.uniform(2, 15))
        self.last_activity = self.t
        return True

    # ---------- run ----------
    def run(self) -> dict:
        r = self.r
        for step in self.pb["steps"]:
            if step.get("when") and step["when"] != self.variant:
                continue
            if "p" in step:
                did = self.did()
                if rails.decide(self.w, r, decision_id=did, ts=self.t, agent=self.crew.crew_id, kind="crew_step",
                                journey_id=self.jid, step=step["id"], step_no=self.step_no[step["id"]], p=step["p"],
                                inputs={"p_step": step["p"]},
                                forced="yes" if self.is_demo and step["id"] != "come_back" else None) == "no":
                    continue
            self.t += timedelta(minutes=draw(r, step.get("gap_min", 0)))
            reps = int(draw(r, step.get("repeat", 1))) if "ask" not in step else 1
            alive = True
            for k in range(reps):
                if k:
                    self.t += timedelta(minutes=draw(r, step.get("repeat_gap_min", [60, 600])))
                cause = None
                if "decide" in step and k == reps - 1:
                    self.events(step, self.last_cause)
                    out, cause = self.victim(step["id"], step["decide"]["pressure"])
                    self.complied += out == "comply"
                    if out != "comply":
                        self.outcome = f"refused_at:{step['id']}"
                        alive = False
                        break
                else:
                    self.events(step, self.last_cause)
                if "crew_pays" in step:
                    self.crew_pays(step["crew_pays"], cause)
            if not alive:
                break
            if "ask" in step:
                for k in range(int(draw(r, step["ask"].get("repeat", 1)))):
                    if k:
                        self.t += timedelta(minutes=draw(r, step.get("gap_min", [60, 600])))
                    if not self.ask(step, step["ask"]):
                        alive = False
                        break
            if not alive:
                break
            self.last_activity = max(self.last_activity, self.t)
        return self.row()

    def row(self) -> dict:
        return {"journey_id": self.jid, "user_id": self.user["user_id"], "playbook": self.pb_name,
                "started_at": self.start, "last_payment_at": max((p[0] for p in self.payments), default=None),
                "caller_number": self.caller, "mule_upi_ids": ",".join(self.mules), "n_payments": len(self.payments),
                "total_paid": float(self.paid), "is_demo": self.is_demo, "reported": False, "variant": self.variant,
                "outcome": self.outcome, "crew_id": self.crew.crew_id, "last_activity": self.last_activity,
                "complied_steps": self.complied}
