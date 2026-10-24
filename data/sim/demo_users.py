"""Demo accounts for Cache Pay's "Use a demo account" button, taken from the simulated world.

    PYTHONPATH=backend:ml:data python -m sim.demo_users --data data/          # print them
    PYTHONPATH=backend:ml:data python -m sim.demo_users --data data/ --write  # update the app's asset

Each account is a real user of the world (users.parquet + accounts.parquet), so the server's
history for that user_id (baselines, known payees) matches what the phone shows. Details the world
does not hold (date of birth, e-mail, IFSC, last 4 digits) are made up from the user's own record,
the same way every time. Age, gender and language never feed a decision (rule 14).
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import pandas as pd

from .accounts import DEMO_MEENA

DEMO_USERS = [DEMO_MEENA, "u_001435"]      # Meena Kulkarni (Pune, 60+), Rahul Yadav (Bengaluru, 18-29)
ASSET = Path(__file__).resolve().parents[2] / "android" / "app" / "src" / "main" / "assets" / "demo_users.json"
TODAY = date(2026, 10, 24)                  # fixed, so the asset never changes on its own

IFSC_PREFIX = {
    "State Bank of India": "SBIN", "HDFC Bank": "HDFC", "ICICI Bank": "ICIC", "Axis Bank": "UTIB",
    "Kotak Mahindra Bank": "KKBK", "IndusInd Bank": "INDB", "Punjab National Bank": "PUNB",
    "Bank of Baroda": "BARB", "Yes Bank": "YESB", "Paytm Payments Bank": "PYTM",
    "Airtel Payments Bank": "AIRP", "Canara Bank": "CNRB", "Union Bank of India": "UBIN",
}
AGE_MIDDLE = {"18-29": 24, "30-44": 37, "45-59": 52, "60+": 66}


def demo_users(data: Path, user_ids: list[str] = DEMO_USERS) -> list[dict]:
    users = pd.read_parquet(data / "users.parquet").set_index("user_id")
    acc = pd.read_parquet(data / "accounts.parquet").set_index("upi_id")
    out = []
    for uid in user_ids:
        u = users.loc[uid]
        a = acc.loc[u.upi_id]
        digits = "".join(c for c in a.account_id if c.isdigit()).rjust(6, "0")
        name = str(a.holder_name)
        out.append({
            "user_id": uid,
            "full_name": name,
            "mobile": str(u.mobile)[-10:],
            "email": ".".join(name.lower().split()) + "@example.com",
            "date_of_birth": TODAY.replace(year=TODAY.year - AGE_MIDDLE[u.age_band], month=6, day=15).isoformat(),
            "language": str(u.language),
            "region": str(u.region),
            "bank_name": str(a.bank),
            "account_last4": digits[-4:],
            "ifsc": IFSC_PREFIX.get(str(a.bank), "CPAY") + "0" + digits[-6:],
            "upi_id": str(u.upi_id),
        })
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data", type=Path, default=Path("data"))
    p.add_argument("--user", action="append", help="user_id to include (repeatable); default: the demo users")
    p.add_argument("--write", action="store_true", help=f"write {ASSET.name} into the app's assets")
    a = p.parse_args()
    users = demo_users(a.data, a.user or DEMO_USERS)
    text = json.dumps(users, indent=2, ensure_ascii=False) + "\n"
    if a.write:
        ASSET.write_text(text, encoding="utf-8")
        print(f"wrote {len(users)} demo users to {ASSET}")
    else:
        print(text)


if __name__ == "__main__":
    main()
