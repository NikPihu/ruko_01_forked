"""Everyday UPI life plus the harmless look-alikes (hard negatives) a scam detector must not flag."""
from __future__ import annotations

from datetime import timedelta

from .names import REMOTE_ACCESS_PKGS
from .world import World

SPAM_TAGS = ("kyc", "trading_tip", "task_job", "refund")


def build_normal_life(w: World) -> None:
    cfg, rng = w.cfg, w.rng
    all_kirana = [k for ks in w.kirana_by_region.values() for k in ks]

    for d in range(cfg.n_days):
        day = cfg.start + timedelta(days=d)
        for u in w.users:
            s, me = u["scale"], u["upi_id"]

            # Groceries: small, frequent, mostly the same 1-3 neighbourhood shops.
            if rng.random() < 0.6:
                for _ in range(rng.choice((1, 1, 2))):
                    if rng.random() < 0.85:
                        shop, entry = rng.choice(u["kiranas"]), "qr"
                    else:
                        shop, entry = rng.choice(w.kirana_by_region[u["region"]] or all_kirana), "qr"
                    w.pay(w.day_time(day), me, shop, w.lognormal_amount(150 * s, 0.7, 10, 3000),
                          entry, "normal")

            if rng.random() < 0.05:
                w.pay(w.day_time(day), me, rng.choice(w.pharmacies),
                      w.lognormal_amount(400 * s, 0.6, 50, 5000), "qr", "normal")

            # Hard negative: a large, first-time payment to a verified hospital.
            if rng.random() < 0.0015:
                w.pay(w.day_time(day), me, rng.choice(w.hospitals),
                      w.lognormal_amount(25000, 0.6, 5000, 100000), "qr", "normal")

            # Family transfers, sometimes while on a long call with that family member.
            if rng.random() < 0.08:
                i = rng.randrange(len(u["family"]))
                ts = w.day_time(day)
                if rng.random() < 0.3:
                    w.call(ts - timedelta(minutes=rng.uniform(2, 20)), u["user_id"],
                           u["family_mobiles"][i], rng.uniform(10, 45), in_contacts=True)
                w.pay(ts, me, u["family"][i], w.lognormal_amount(2000 * s, 0.8, 200, 50000),
                      "contact", "normal")

            if day.day == u["bill_day"]:
                for biller in w.billers[:2]:
                    w.pay(w.day_time(day), me, biller, w.lognormal_amount(800 * s, 0.5, 100, 6000),
                          "typed", "normal")
            if u["landlord"] and day.day == u["rent_day"]:
                w.pay(w.day_time(day), me, u["landlord"], w.lognormal_amount(12000 * s, 0.3, 3000, 60000),
                      "contact", "normal")
            # Hard negative: migrant remittance, monthly, large relative to other spending.
            if u["remits"] and day.day == 1:
                w.pay(w.day_time(day), me, u["family"][0], w.lognormal_amount(8000 * s, 0.4, 2000, 40000),
                      "contact", "normal")

            _context_noise(w, u, day)


def _context_noise(w: World, u: dict, day) -> None:
    """Unknown calls, spam lures and legit remote-access installs that happen to honest people."""
    rng = w.rng
    if rng.random() < 0.25:  # delivery agents, banks, wrong numbers
        w.call(w.day_time(day), u["user_id"], w.new_mobile(), rng.uniform(0.5, 4), in_contacts=False)
    if rng.random() < 0.3:
        i = rng.randrange(len(u["family_mobiles"]))
        w.call(w.day_time(day), u["user_id"], u["family_mobiles"][i], rng.uniform(1, 40), in_contacts=True)
    if rng.random() < 0.03:
        w.event(w.day_time(day), u["user_id"], "sms_lure",
                {"tag": rng.choice(SPAM_TAGS), "conf": round(rng.uniform(0.5, 0.9), 2)})
    # About 1% of users install a remote-access tool once in the window for real IT support.
    if rng.random() < 0.01 / w.cfg.n_days:
        w.event(w.day_time(day), u["user_id"], "app_installed",
                {"pkg": rng.choice(REMOTE_ACCESS_PKGS), "is_remote_access": True, "sideloaded": False})
