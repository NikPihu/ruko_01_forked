"""Accounts behind UPI IDs: people, shops, hospitals, billers, mules, cash-out accounts.

Every account is reachable only by its UPI ID (and, for some, its mobile number), the same two
identifiers a payer's app sees in reality.
"""
from __future__ import annotations

from datetime import timedelta

from .config import HANDLES
from .names import REGIONS, SHOP_WORDS
from .world import World

DEMO_MEENA = "u_demo_meena"
DEMO_KIRANA_UPI = "shreeganesh.kirana@okaxis"
DEMO_MULE_UPI = "secure.settlement.desk@okaxis"

AGE_BANDS = ("18-29", "30-44", "45-59", "60+")


def _years_ago(w: World, lo: float, hi: float):
    return w.cfg.start - timedelta(days=w.rng.uniform(lo, hi) * 365)


def _person_upi(w: World, first: str, last: str, mobile: str, handle: str) -> str:
    # About a third of people use their number as the UPI ID (e.g. 98xxxxxx10@ybl).
    if w.rng.random() < 0.33:
        return w.new_upi(mobile[-10:], handle)
    return w.new_upi(f"{first}.{last}", handle)


def _add_user(w: World, user_id: str, region: str, age_band: str, language: str,
              first: str | None = None, last: str | None = None) -> dict:
    if first is None:
        first, last = w.person_name()
    h = w.pick_handle()
    mobile = w.new_mobile()
    created = _years_ago(w, 1, 8)
    acct = w.add_account(
        upi_id=_person_upi(w, first, last, mobile, h.handle), mobile=mobile, handle=h.handle,
        bank=h.bank, partner_bank=h.partner, holder_name=f"{first.title()} {last.title()}",
        holder_type="person", merchant_kind=None, mcc=None, verified=False,
        created_at=created, kyc_at=created, region=region, is_mule=False, mule_kind=None)
    user = {"user_id": user_id, "upi_id": acct["upi_id"], "mobile": mobile, "region": region,
            "age_band": age_band, "language": language,
            # Spending scale: multiplies every normal-life amount for this user.
            "scale": w.rng.lognormvariate(0, 0.5)}
    w.users.append(user)
    w.users_by_id[user_id] = user
    return user


def _add_merchant(w: World, kind: str, region: str, mcc: str, verified: bool,
                  upi_id: str | None = None, name: str | None = None) -> dict:
    h = w.pick_handle()
    last = w.rng.choice(("sharma", "gupta", "jain", "patel", "agarwal", "shetty", "reddy"))
    if name is None:
        name = {"kirana": f"{last.title()} {w.rng.choice(SHOP_WORDS).title()}",
                "pharmacy": f"{last.title()} Medicals",
                "hospital": f"{region} {w.rng.choice(('City', 'Care', 'Life'))} Hospital",
                "biller": w.rng.choice(("Power Distribution Co", "Telecom Postpaid", "Gas Agency"))}[kind]
    if upi_id is None:
        upi_id = w.new_upi(name.lower().replace(" ", ""), h.handle)
    else:
        w._used_upi.add(upi_id)
        h = next(x for x in HANDLES if x.handle == upi_id.split("@")[1])
    created = _years_ago(w, 1, 10)
    return w.add_account(
        upi_id=upi_id, mobile=w.new_mobile(), handle=h.handle, bank=h.bank,
        partner_bank=h.partner, holder_name=name, holder_type="merchant", merchant_kind=kind,
        mcc=mcc, verified=verified, created_at=created, kyc_at=created, region=region,
        is_mule=False, mule_kind=None)


def _add_mule(w: World, kind: str, upi_id: str | None = None, created=None) -> dict:
    """A mule account: opened in someone's name (often recently) to receive and forward scam money."""
    first, last = w.person_name()
    h = w.pick_handle()
    mobile = w.new_mobile()
    if created is None:
        # Spread openings so some mules exist before the window starts and some appear inside it.
        created = w.cfg.start + timedelta(days=w.rng.uniform(-25, w.cfg.n_days - 5))
    if kind == "merchant_disguised":
        name = f"{last.title()} {w.rng.choice(SHOP_WORDS).title()}"
        holder_type, mcc, merchant_kind = "merchant", "5411", "kirana"
        upi_id = upi_id or w.new_upi(name.lower().replace(" ", ""), h.handle)
    else:
        name = f"{first.title()} {last.title()}"
        holder_type, mcc, merchant_kind = "person", None, None
        upi_id = upi_id or _person_upi(w, first, last, mobile, h.handle)
    if upi_id in w.by_upi:
        raise ValueError(upi_id)
    w._used_upi.add(upi_id)
    h = next(x for x in HANDLES if x.handle == upi_id.split("@")[1])
    acct = w.add_account(
        upi_id=upi_id, mobile=mobile, handle=h.handle, bank=h.bank, partner_bank=h.partner,
        holder_name=name, holder_type=holder_type, merchant_kind=merchant_kind, mcc=mcc,
        verified=False, created_at=created, kyc_at=created, region=w.rng.choice(REGIONS),
        is_mule=True, mule_kind=kind)
    # Warm-up mules are groomed with small inflows for two weeks before first scam use.
    acct["_active_from"] = created + timedelta(days=14 if kind == "warm_up" else 0)
    return acct


def build_accounts(w: World) -> None:
    cfg, rng = w.cfg, w.rng

    # People.
    _add_user(w, DEMO_MEENA, "Pune", "60+", "hi", "meena", "kulkarni")
    for i in range(cfg.n_users - 1):
        _add_user(w, f"u_{i:06d}", rng.choice(REGIONS),
                  rng.choices(AGE_BANDS, weights=(30, 35, 22, 13))[0],
                  rng.choices(("en", "hi"), weights=(55, 45))[0])

    # Shops and services. Every region gets at least one kirana.
    w.kirana_by_region = {r: [] for r in REGIONS}
    demo = _add_merchant(w, "kirana", "Pune", "5411", True,
                         upi_id=DEMO_KIRANA_UPI, name="Shree Ganesh Kirana")
    w.kirana_by_region["Pune"].append(demo["upi_id"])
    for i in range(cfg.n_kirana):
        region = REGIONS[i % len(REGIONS)]
        m = _add_merchant(w, "kirana", region, "5411", rng.random() < 0.6)
        w.kirana_by_region[region].append(m["upi_id"])
    for _ in range(max(3, cfg.n_users // 100)):
        w.pharmacies.append(_add_merchant(w, "pharmacy", rng.choice(REGIONS), "5912", True)["upi_id"])
    for _ in range(max(2, cfg.n_users // 400)):
        w.hospitals.append(_add_merchant(w, "hospital", rng.choice(REGIONS), "8062", True)["upi_id"])
    for mcc in ("4900", "4814", "5983"):
        w.billers.append(_add_merchant(w, "biller", "Mumbai", mcc, True)["upi_id"])

    # Mules. The demo mule is fresh (4 days old) at a partner bank and never reported in-window.
    w.mules.append(_add_mule(w, "plain", upi_id=DEMO_MULE_UPI, created=cfg.end - timedelta(days=4)))
    kinds, weights = zip(*cfg.mule_kind_weights.items())
    for _ in range(cfg.n_mules - 1):
        w.mules.append(_add_mule(w, rng.choices(kinds, weights=weights)[0]))
    # Cash-out accounts: second-layer mules that receive forwarded money.
    for _ in range(cfg.n_cash_out):
        acct = _add_mule(w, "cash_out", created=cfg.start - timedelta(days=rng.uniform(5, 60)))
        w.cash_out.append(acct)

    # Outside victims: real-looking people who are not users of our app.
    for _ in range(max(100, cfg.n_users // 2)):
        first, last = w.person_name()
        h = w.pick_handle()
        mobile = w.new_mobile()
        created = _years_ago(w, 1, 10)
        w.external.append(w.add_account(
            upi_id=_person_upi(w, first, last, mobile, h.handle), mobile=mobile, handle=h.handle,
            bank=h.bank, partner_bank=h.partner, holder_name=f"{first.title()} {last.title()}",
            holder_type="person", merchant_kind=None, mcc=None, verified=False,
            created_at=created, kyc_at=created, region=rng.choice(REGIONS), is_mule=False,
            mule_kind=None))

    # Scammer phone lines: some foreign VoIP numbers, some rotated Indian SIMs.
    w.scam_numbers = [w.foreign_or_local_number(0.4) for _ in range(max(5, cfg.n_journeys // 2))]

    # Family links (same region preferred) and household patterns.
    by_region: dict[str, list[dict]] = {}
    for u in w.users:
        by_region.setdefault(u["region"], []).append(u)
    for u in w.users:
        peers = [p for p in by_region[u["region"]] if p is not u] or [p for p in w.users if p is not u]
        u["family"] = [p["upi_id"] for p in rng.sample(peers, k=min(len(peers), rng.randint(2, 4)))]
        u["family_mobiles"] = [w.by_upi[x]["mobile"] for x in u["family"]]
        u["landlord"] = rng.choice(peers)["upi_id"] if rng.random() < 0.3 else None
        u["rent_day"] = rng.randint(1, 5)
        u["bill_day"] = rng.randint(5, 25)
        u["remits"] = rng.random() < 0.15
        local = w.kirana_by_region[u["region"]]
        u["kiranas"] = rng.sample(local, k=min(len(local), rng.randint(1, 3)))
        if u["region"] == "Pune" and DEMO_KIRANA_UPI not in u["kiranas"]:
            # The demo shop is the neighbourhood store for most of Pune: high fan-in, high repeat.
            if rng.random() < 0.8:
                u["kiranas"][0] = DEMO_KIRANA_UPI

    # Final, shuffled account ids so mules are not clustered at the end.
    order = list(range(len(w.accounts)))
    rng.shuffle(order)
    for new_id, idx in enumerate(order):
        w.accounts[idx]["account_id"] = f"a_{new_id:06d}"
    for u in w.users:
        u["account_id"] = w.by_upi[u["upi_id"]]["account_id"]
