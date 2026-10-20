"""Scam journeys: timed context events and payments, labelled with the stage (S1..S5).

Stages: S1 contacted, S2 hooked, S3 under control, S4 paying, S5 repeat payment.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .accounts import DEMO_MEENA, DEMO_MULE_UPI
from .config import P2P_TXN_CAP
from .names import REMOTE_ACCESS_PKGS
from .world import World

AGE_WEIGHT = {"18-29": 1.0, "30-44": 1.2, "45-59": 2.0, "60+": 3.0}


@dataclass
class Journey:
    jid: str
    user: dict
    playbook: str
    start: datetime
    caller: str | None = None
    mules: list[str] = field(default_factory=list)
    payments: list[dict] = field(default_factory=list)
    is_demo: bool = False
    variant: str | None = None


def _pay(w: World, j: Journey, ts: datetime, mule: str, amount: float, entry: str) -> None:
    stage = "S4" if not j.payments else "S5"
    row = w.pay(ts, j.user["upi_id"], mule, min(int(amount), P2P_TXN_CAP), entry, "scam",
                journey_id=j.jid, is_scam=True, stage=stage)
    if row:
        j.payments.append(row)
        if mule not in j.mules:
            j.mules.append(mule)


def _tranches(w: World, total: float, max_n: int) -> list[int]:
    n = w.rng.randint(1, max_n)
    n = max(n, -(-int(total) // P2P_TXN_CAP))  # enough tranches to stay under the cap
    cuts = sorted(w.rng.random() for _ in range(n - 1))
    parts = [b - a for a, b in zip([0.0, *cuts], [*cuts, 1.0])]
    return [max(500, round(total * p, -2)) for p in parts]


def _remote_control(w: World, j: Journey, ts: datetime) -> None:
    pkg = w.rng.choice(REMOTE_ACCESS_PKGS)
    uid = j.user["user_id"]
    w.event(ts, uid, "app_installed", {"pkg": pkg, "is_remote_access": True, "sideloaded": False},
            j.jid, "S3")
    w.event(ts + w.uniform_td(1, 5), uid, "remote_session_notice", {"pkg": pkg}, j.jid, "S3")


def digital_arrest(w: World, j: Journey, mule2: str) -> None:
    rng, uid, t0 = w.rng, j.user["user_id"], j.start
    if rng.random() < 0.3:
        w.event(t0 - w.uniform_td(60, 1440), uid, "sms_lure",
                {"tag": "arrest_threat", "conf": round(rng.uniform(0.7, 0.95), 2)}, j.jid, "S1")
    voip = j.caller is not None and not j.caller.startswith("+91") or rng.random() < 0.5
    minutes = rng.uniform(45, 180)
    end = w.call(t0, uid, j.caller, minutes, in_contacts=False, kind="voip" if voip else "sim",
                 journey_id=j.jid, stage="S1")
    if rng.random() < 0.6:
        _remote_control(w, j, t0 + w.uniform_td(10, 40))
    ts = t0 + w.uniform_td(30, minutes)
    if rng.random() < 0.2:  # scammer hangs up before the payment ("call memory" still applies)
        ts = end + w.uniform_td(2, 30)
    for i, amt in enumerate(_tranches(w, rng.uniform(50_000, 400_000), 5)):
        _pay(w, j, ts, j.mules[0] if i < 2 or rng.random() < 0.7 else mule2, amt, "typed")
        ts += w.uniform_td(3, 20)
    if rng.random() < 0.35:  # comes back the next day for more
        t1 = t0 + timedelta(days=1, minutes=rng.uniform(-120, 120))
        w.call(t1, uid, j.caller, rng.uniform(20, 90), in_contacts=False,
               kind="voip" if voip else "sim", journey_id=j.jid, stage="S5")
        for amt in _tranches(w, rng.uniform(20_000, 150_000), 2):
            t1 += w.uniform_td(10, 30)
            _pay(w, j, t1, mule2, amt, "typed")


def trading_group(w: World, j: Journey, mule2: str) -> None:
    rng, uid, t = w.rng, j.user["user_id"], j.start
    for i in range(rng.randint(2, 5)):
        w.event(t, uid, "notification_lure", {"tag": "trading_tip", "conf": round(rng.uniform(0.6, 0.9), 2)},
                j.jid, "S1" if i == 0 else "S2")
        t += timedelta(hours=rng.uniform(6, 30))
    amt = rng.uniform(2_000, 8_000)
    for i in range(rng.randint(3, 6)):
        _pay(w, j, t, j.mules[0] if i % 2 == 0 else mule2, amt, "typed")
        if i == 0:  # fake "profit" to build trust
            w.pay(t + timedelta(hours=rng.uniform(2, 12)), rng.choice(w.cash_out)["upi_id"],
                  j.user["upi_id"], round(amt * rng.uniform(0.1, 0.3)), "typed", "scam_bait",
                  journey_id=j.jid)
        amt *= rng.uniform(1.5, 2.5)
        t += timedelta(hours=rng.uniform(8, 40))


def task_job(w: World, j: Journey, mule2: str) -> None:
    rng, uid, t = w.rng, j.user["user_id"], j.start
    # Variant (w.aux, so the core world is unchanged): a crypto "deposit" scam with no rewards first.
    crypto = w.aux.random() < 0.25
    j.variant = "crypto_deposit" if crypto else "rewards"
    conf = round(rng.uniform(0.6, 0.9), 2)
    w.event(t, uid, "sms_lure", {"tag": "trading_tip" if crypto else "task_job", "conf": conf}, j.jid, "S1")
    for _ in range(rng.randint(2, 3)):  # tiny rewards for "liking videos"
        t += timedelta(hours=rng.uniform(1, 6))
        sender, amount = rng.choice(w.cash_out)["upi_id"], rng.randint(50, 300)
        if not crypto:
            w.pay(t, sender, j.user["upi_id"], amount, "typed", "scam_bait", journey_id=j.jid)
    amt = rng.uniform(1_000, 3_000)
    used: list[str] = []
    for i in range(rng.randint(3, 5)):
        t += timedelta(hours=rng.uniform(2, 20))
        # The payee rotates after every payment ("level 2 account", "level 3 account"...).
        fresh = [m for m in _eligible_mules(w, t) if m not in used] or [j.mules[0] if i < 2 else mule2]
        payee = j.mules[0] if i == 0 else w.aux.choice(fresh)
        used.append(payee)
        _pay(w, j, t, payee, amt, "typed")
        amt *= rng.uniform(1.8, 3.0)


def fake_kyc_apk(w: World, j: Journey, mule2: str) -> None:
    rng, uid, t = w.rng, j.user["user_id"], j.start
    w.event(t, uid, "sms_lure", {"tag": "kyc", "conf": round(rng.uniform(0.7, 0.95), 2), "has_link": True},
            j.jid, "S1")
    pkg = f"com.kyc.update{rng.randrange(1000)}"
    t += w.uniform_td(5, 60)
    w.event(t, uid, "app_installed", {"pkg": pkg, "is_remote_access": False, "sideloaded": True}, j.jid, "S3")
    w.event(t + w.uniform_td(1, 5), uid, "accessibility_enabled", {"pkg": pkg}, j.jid, "S3")
    if rng.random() < 0.5:
        w.call(t + w.uniform_td(5, 30), uid, j.caller, rng.uniform(5, 25), in_contacts=False,
               journey_id=j.jid, stage="S2")
    t += w.uniform_td(30, 360)
    for amt in _tranches(w, rng.uniform(10_000, 150_000), 3):
        _pay(w, j, t, j.mules[0], amt, "typed")
        t += w.uniform_td(2, 15)


def refund_qr(w: World, j: Journey, mule2: str) -> None:
    rng, uid, t = w.rng, j.user["user_id"], j.start
    minutes = rng.uniform(5, 20)
    w.call(t, uid, j.caller, minutes, in_contacts=False, journey_id=j.jid, stage="S1")
    t += w.uniform_td(2, minutes)
    for _ in range(rng.randint(1, 3)):
        _pay(w, j, t, j.mules[0], rng.uniform(2_000, 25_000), "qr")
        t += w.uniform_td(2, 8)


def fake_customer_care(w: World, j: Journey, mule2: str) -> None:
    rng, uid, t = w.rng, j.user["user_id"], j.start
    minutes = rng.uniform(15, 60)
    # The victim calls a fake helpline number found online.
    w.call(t, uid, j.caller, minutes, in_contacts=False, direction="outgoing",
           journey_id=j.jid, stage="S1")
    if rng.random() < 0.8:
        _remote_control(w, j, t + w.uniform_td(5, 15))
    t += w.uniform_td(10, minutes)
    for amt in _tranches(w, rng.uniform(5_000, 80_000), 2):
        _pay(w, j, t, j.mules[0], amt, "typed")
        t += w.uniform_td(2, 10)


PLAYBOOKS = {
    "digital_arrest": digital_arrest, "trading_group": trading_group, "task_job": task_job,
    "fake_kyc_apk": fake_kyc_apk, "refund_qr": refund_qr, "fake_customer_care": fake_customer_care,
}


def _eligible_mules(w: World, at: datetime, exclude_demo: bool = True) -> list[str]:
    ok = [m["upi_id"] for m in w.mules
          if m["_active_from"] <= at and not (exclude_demo and m["upi_id"] == DEMO_MULE_UPI)]
    return ok or [min(w.mules[1:] or w.mules, key=lambda m: m["_active_from"])["upi_id"]]


def build_scams(w: World) -> list[Journey]:
    cfg, rng = w.cfg, w.rng
    victims = [u for u in w.users if u["user_id"] != DEMO_MEENA]
    weights = [AGE_WEIGHT[u["age_band"]] for u in victims]
    names, pw = zip(*cfg.playbook_weights.items())
    journeys: list[Journey] = []

    def run(j: Journey) -> None:
        pool = _eligible_mules(w, j.start)
        if not j.mules:
            j.mules.append(rng.choice(pool))
        PLAYBOOKS[j.playbook](w, j, rng.choice(pool))
        journeys.append(j)

    chosen = set()
    for i in range(cfg.n_journeys):
        user = rng.choices(victims, weights=weights)[0]
        while user["user_id"] in chosen and len(chosen) < len(victims):
            user = rng.choices(victims, weights=weights)[0]
        chosen.add(user["user_id"])
        start = cfg.start + timedelta(minutes=rng.uniform(0, (cfg.n_days - 0.25) * 1440))
        start = start.replace(hour=rng.randint(9, 19))
        run(Journey(f"j_{i:05d}", user, rng.choices(names, weights=pw)[0], start,
                    caller=rng.choice(w.scam_numbers)))

    # Fresh-mule demo: three digital-arrest victims paid the demo mule in the last two days.
    for k in range(3):
        user = rng.choice([u for u in victims if u["user_id"] not in chosen])
        chosen.add(user["user_id"])
        start = cfg.end - timedelta(hours=rng.uniform(8, 46))
        j = Journey(f"j_demo_{k}", user, "digital_arrest", start,
                    caller=rng.choice(w.scam_numbers), mules=[DEMO_MULE_UPI], is_demo=True)
        PLAYBOOKS["digital_arrest"](w, j, DEMO_MULE_UPI)
        journeys.append(j)

    for j in journeys:
        w.journeys.append({
            "journey_id": j.jid, "user_id": j.user["user_id"], "playbook": j.playbook,
            "started_at": j.start,
            "last_payment_at": max((p["ts"] for p in j.payments), default=None),
            "caller_number": j.caller, "mule_upi_ids": ",".join(j.mules),
            "n_payments": len(j.payments), "total_paid": float(sum(p["amount"] for p in j.payments)),
            "is_demo": j.is_demo, "reported": False, "variant": j.variant,
        })
    return journeys
