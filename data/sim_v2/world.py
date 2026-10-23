"""The population: users, their contacts, shops per locality, billers, platforms, crews' accounts.

Everything is created from keyed streams, so user u_000123 (and her shops, contacts and landlord)
is identical in a 500-user and a 20,000-user world. Localities hold 250 users and their shops.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sim_v2.core.config import Config
from sim_v2.core.rng import R, stream
from sim_v2.core.tables import Buffer

# handle: bank, app, partner bank (shares data with RUKO's mock), share of accounts (NPCI-like mix)
HANDLES = {
    "ybl": ("Yes Bank", "PhonePe", False, 0.30), "paytm": ("Paytm Payments Bank", "Paytm", False, 0.12),
    "oksbi": ("State Bank of India", "Google Pay", True, 0.12), "okaxis": ("Axis Bank", "Google Pay", True, 0.10),
    "okhdfcbank": ("HDFC Bank", "Google Pay", True, 0.08), "okicici": ("ICICI Bank", "Google Pay", False, 0.08),
    "ibl": ("IndusInd Bank", "PhonePe", False, 0.10), "axl": ("Axis Bank", "PhonePe", True, 0.10),
}
FIRST = ("aarav", "vivaan", "aditya", "arjun", "sai", "rohan", "rahul", "amit", "vikas", "suresh", "ramesh",
         "manoj", "anil", "sunil", "deepak", "rajesh", "sanjay", "ajay", "kiran", "nikhil", "priya", "ananya",
         "diya", "isha", "kavya", "meena", "sunita", "anita", "pooja", "neha", "rekha", "geeta", "lakshmi",
         "sneha", "shalini", "asha", "usha", "radha", "savita", "nisha")
LAST = ("sharma", "verma", "gupta", "singh", "kumar", "patel", "shah", "jain", "mehta", "joshi", "kulkarni",
        "deshpande", "patil", "pawar", "rao", "reddy", "nair", "iyer", "das", "ghosh", "yadav", "mishra",
        "pandey", "tiwari", "chauhan", "thakur", "naik", "shetty", "bose", "sinha")
REGIONS = ("Pune", "Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai", "Kolkata", "Jaipur", "Lucknow",
           "Patna", "Indore", "Nagpur")
SHOP_WORDS = ("kirana", "general", "store", "provision", "mart", "traders")
# locality shops: kind, mcc, count, verified share
SHOPS = (("kirana", "5411", 6, 0.6), ("pharmacy", "5912", 1, 1.0), ("shop", "5311", 4, 0.5),
         ("shop", "5812", 3, 0.4), ("shop", "5541", 1, 0.8))
BILLERS = (("Power Distribution Co", "4900"), ("Telecom Postpaid", "4814"), ("Gas Agency", "5983"))
PLATFORMS = ("Swift Delivery Partners", "QuickRide Driver Payouts")
REMOTE_PKGS = ("com.anydesk.anydeskandroid", "com.teamviewer.quicksupport.market", "com.carriez.flutter_hbb",
               "com.sand.airdroid")
FOREIGN_CODES = ("+92", "+855", "+880", "+971", "+84")


@dataclass
class World:
    cfg: Config
    accounts: dict = field(default_factory=dict)     # upi_id -> account row
    users: list = field(default_factory=list)
    localities: dict = field(default_factory=dict)   # index -> {region, shops, kiranas, ...}
    billers: list = field(default_factory=list)
    platforms: list = field(default_factory=list)
    journeys: list = field(default_factory=list)
    reports: list = field(default_factory=list)
    mule_inflows: list = field(default_factory=list)  # (ts, mule, amount, key) to forward later
    crews: dict = field(default_factory=dict)
    external_reports: list = field(default_factory=list)   # (ts, mule, crew) outside victims' payments
    collection_inflows: list = field(default_factory=list)  # (ts, fund, amount, locality)
    demo_cash_out: str | None = None
    ledger: Buffer = field(default_factory=lambda: Buffer("ledger"))
    events: Buffer = field(default_factory=lambda: Buffer("context_events"))
    decisions: Buffer = field(default_factory=lambda: Buffer("decisions"))

    def __post_init__(self):
        self.seed = self.cfg.seed
        self.start, self.end = self.cfg.start, self.cfg.end
        self.hour_p = self.cfg.get("routine.hour_profile")

    def r(self, *key) -> R:
        return stream(self.seed, *key)

    # ---------- identities ----------
    def handle(self, r: R, prefer: str | None = None) -> str:
        if prefer:
            return prefer
        return r.choice(list(HANDLES), [v[3] for v in HANDLES.values()])

    @staticmethod
    def mobile(r: R, country: str = "+91") -> str:
        if country == "+91":
            return "+91" + str(r.integer(6, 9)) + "".join(str(r.integer(0, 9)) for _ in range(9))
        return country + "".join(str(r.integer(0, 9)) for _ in range(10))

    def add_account(self, upi_id: str, *, holder_name: str, holder_type: str, created_at: datetime, region: str,
                    mobile: str, merchant_kind=None, mcc=None, verified=False, is_mule=False, mule_kind=None) -> dict:
        upi_id = upi_id.lower()
        while upi_id in self.accounts:   # rare name / number clash: deterministic suffix
            local, h = upi_id.split("@")
            upi_id = f"{local}1@{h}"
        h = upi_id.split("@")[1]
        bank, _, partner, _ = HANDLES[h]
        acct = {"account_id": None, "upi_id": upi_id, "mobile": mobile, "handle": h, "bank": bank,
                "partner_bank": partner, "holder_name": holder_name, "holder_type": holder_type,
                "merchant_kind": merchant_kind, "mcc": mcc, "verified": verified, "created_at": created_at,
                "kyc_at": created_at, "region": region, "is_mule": is_mule, "mule_kind": mule_kind}
        self.accounts[upi_id] = acct
        return acct

    def person(self, key: tuple, region: str, age_days: float | None = None, handle: str | None = None,
               tag: str = "") -> dict:
        """A person's account. `key` names it uniquely, e.g. ('contact', 'u_000123', 3)."""
        r = self.r("person", *key)
        first, last = r.choice(FIRST), r.choice(LAST)
        h = self.handle(r, handle)
        mobile = self.mobile(r)
        if age_days is None:
            new = r.chance(self.cfg.get("routine.new_account_share"))
            age_days = r.uniform(3, 90) if new else r.uniform(90, 3650)
        suffix = abs(hash_key(key)) % 100000
        upi = f"{mobile[-10:]}@{h}" if r.chance(0.33) else f"{first}.{last}{tag}{suffix}@{h}"
        return self.add_account(upi, holder_name=f"{first.title()} {last.title()}", holder_type="person",
                                created_at=self.start - timedelta(days=age_days), region=region, mobile=mobile)

    def merchant(self, key: tuple, kind: str, mcc: str, region: str, verified: bool, name: str | None = None,
                 upi_id: str | None = None, age_days: float | None = None) -> dict:
        r = self.r("merchant", *key)
        last = r.choice(("sharma", "gupta", "jain", "patel", "agarwal", "shetty", "reddy", "khan", "rao"))
        name = name or {"kirana": f"{last.title()} {r.choice(SHOP_WORDS).title()}",
                        "pharmacy": f"{last.title()} Medicals", "hospital": f"{region} {r.choice(('City', 'Care', 'Life'))} Hospital",
                        "shop": f"{last.title()} {r.choice(('Mobiles', 'Fashion', 'Eatery', 'Fuels', 'Hardware', 'Bakery'))}"}.get(kind, kind)
        h = self.handle(r)
        upi_id = upi_id or f"{name.lower().replace(' ', '')}{abs(hash_key(key)) % 1000}@{h}"
        if age_days is None:
            age_days = r.uniform(30, 900) if r.chance(0.15) else r.uniform(365, 3650)
        return self.add_account(upi_id, holder_name=name, holder_type="merchant", merchant_kind=kind, mcc=mcc,
                                verified=verified, created_at=self.start - timedelta(days=age_days), region=region,
                                mobile=self.mobile(r))

    # ---------- build ----------
    def build_population(self) -> None:
        cfg = self.cfg
        n_loc = max(1, math.ceil(cfg.users / cfg.users_per_locality))
        for l in range(n_loc):
            self.locality(l)
        for i, (name, mcc) in enumerate(BILLERS):
            self.billers.append(self.merchant(("biller", i), "biller", mcc, "Mumbai", True, name=name,
                                              age_days=3000)["upi_id"])
        for i, name in enumerate(PLATFORMS):
            self.platforms.append(self.merchant(("platform", i), "platform", "4121", "Mumbai", True, name=name,
                                                age_days=2500)["upi_id"])
        demo = cfg.demo["meena"]
        self.users.append(self.user(-1, 0, scripted=demo))
        for i in range(cfg.users - 1):
            self.users.append(self.user(i, i // cfg.users_per_locality))

    def locality(self, l: int) -> dict:
        region = REGIONS[l % len(REGIONS)]
        loc = {"index": l, "region": region, "kiranas": [], "shops": [], "pharmacy": [], "hospital": []}
        if region == "Pune":   # the demo kirana is the main shop of every Pune locality
            k = self.cfg.demo["kirana"]
            if k["upi_id"] not in self.accounts:
                self.merchant(("demo_kirana",), "kirana", "5411", "Pune", True, name=k["name"], upi_id=k["upi_id"],
                              age_days=2200)
            loc["kiranas"].append(k["upi_id"])
        r = self.r("locality", l)
        for kind, mcc, count, ver in SHOPS:
            for c in range(count):
                m = self.merchant(("loc", l, kind, mcc, c), kind, mcc, region, r.chance(ver))
                loc["kiranas" if kind == "kirana" else "pharmacy" if kind == "pharmacy" else "shops"].append(m["upi_id"])
        if l % 2 == 0:
            loc["hospital"].append(self.merchant(("loc", l, "hospital"), "hospital", "8062", region, True)["upi_id"])
        else:
            loc["hospital"] = self.localities[l - 1]["hospital"]
        coll = self.person(("collection", l), region, age_days=r.uniform(400, 2000), tag="fund")
        coll["holder_name"] = f"{region} {r.choice(('Society', 'Mandal', 'Residents'))} Fund"
        loc["collection"] = coll["upi_id"]
        loc["vendor"] = loc["shops"][0]
        self.localities[l] = loc
        return loc

    def user(self, i: int, l: int, scripted: dict | None = None) -> dict:
        cfg, loc = self.cfg, self.localities[l]
        uid = scripted["user_id"] if scripted else f"u_{i:06d}"
        r = self.r("user", uid)
        personas = cfg.get("population.personas")
        persona = scripted["persona"] if scripted else r.weighted({k: v["share"] for k, v in personas.items()})
        p = personas[persona]
        age_band = scripted["age_band"] if scripted else r.weighted(p["ages"])
        if scripted:
            acct = self.add_account(scripted["upi_id"], holder_name=scripted["name"], holder_type="person",
                                    created_at=self.start - timedelta(days=1800), region=loc["region"],
                                    mobile=scripted["mobile"])
        else:
            acct = self.person(("user", uid), loc["region"], age_days=r.uniform(120, 3000))
        cons = cfg.get("population.consent")
        k_lo, k_hi = cfg.get("routine.contacts")
        contacts = [self.person(("contact", uid, k), loc["region"])["upi_id"] for k in range(r.integer(k_lo, k_hi))]
        kir = list(loc["kiranas"])
        if loc["region"] == "Pune" and kir[0] == cfg.demo["kirana"]["upi_id"] and not r.chance(cfg.demo["kirana"]["pune_share"]):
            kir = kir[1:] + kir[:1]
        others = loc["kiranas"][1:] + loc["shops"]
        shops = kir[:1] + r.sample(others, r.integer(2, 6))
        return {
            "user_id": uid, "upi_id": acct["upi_id"], "mobile": acct["mobile"], "region": loc["region"],
            "age_band": age_band, "language": scripted["language"] if scripted else ("hi" if r.chance(cfg.get("population.language_hi")) else "en"),
            "sms_consent": scripted["sms_consent"] if scripted else r.chance(cons["sms"]),
            "call_consent": r.chance(cons["call_signals"]), "app_consent": r.chance(cons["app_checks"]),
            "persona": persona, "income_month": round(p["income"] * r.lognormal(1, 0.35)),
            "savings_months": round(r.loguniform(*cfg.get("population.savings_months")), 1),
            "rate": p["rate"] * math.exp(r.g.normal(0, cfg.get("population.activity_sigma"))),
            "locality": l, "contacts": contacts, "shops": shops,
            "landlord": self.person(("landlord", uid), loc["region"])["upi_id"] if r.chance(cfg.get("routine.rent_share")) else None,
            "rent_day": r.integer(1, 5), "bill_day": r.integer(5, 25), "pays_bill": r.chance(cfg.get("routine.bill_share")),
            "never_scammed": bool(scripted and scripted.get("never_scammed")),
        }


def hash_key(key: tuple) -> int:
    import hashlib
    return int.from_bytes(hashlib.blake2b(repr(key).encode(), digest_size=6).digest(), "little")
