"""A demo user's phone address book, from the simulated world, and a way to put it on the emulator.

    PYTHONPATH=backend:ml:data python -m sim.contacts --data data/          # print Meena's contacts
    PYTHONPATH=backend:ml:data python -m sim.contacts --data data/ --adb    # add them to the emulator

The address book holds the people the user really paid or got money from in the world (so their
mobile numbers map to the UPI IDs the bank's history knows), plus a few people never paid, as a
real phone would. Merchants and mules are never in it. Cache Pay reads these from the phone's own
Contacts; only a yes/no "payee is a saved contact" ever leaves the phone (contract c2-0.7).
"""
from __future__ import annotations

import argparse
import os
import random
import shutil
import subprocess
from pathlib import Path

import pandas as pd

from .accounts import DEMO_MEENA

NEVER_PAID = 3          # people in the address book the user has not paid
SEED = 11               # its own random stream, so the world itself never shifts


def address_book(data: Path, user_id: str = DEMO_MEENA) -> list[dict]:
    users = pd.read_parquet(data / "users.parquet").set_index("user_id")
    acc = pd.read_parquet(data / "accounts.parquet")
    ledger = pd.read_parquet(data / "ledger.parquet", columns=["from_upi", "to_upi", "amount"])
    me = users.loc[user_id]
    people = acc[(acc.holder_type == "person") & ~acc.is_mule & (acc.upi_id != me.upi_id)].set_index("upi_id")

    paid = ledger[ledger.from_upi == me.upi_id].groupby("to_upi").amount.agg(["size", "sum"])
    got = ledger[ledger.to_upi == me.upi_id].groupby("from_upi").size()
    known = [u for u in dict.fromkeys([*paid.index, *got.index]) if u in people.index]

    rng = random.Random(SEED)
    pool = sorted(set(people[people.region == me.region].index) - set(known))
    strangers = rng.sample(pool, min(NEVER_PAID, len(pool)))

    book = []
    for upi in [*known, *strangers]:
        p = people.loc[upi]
        book.append({"name": p.holder_name, "mobile": p.mobile, "upi_id": upi,
                     "paid": int(paid["size"].get(upi, 0)), "paid_inr": float(paid["sum"].get(upi, 0.0)),
                     "sent_to_user": int(got.get(upi, 0))})
    return book


# ---------- the emulator's address book, through adb (shell can write Contacts) ----------

def _adb() -> str:
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk" / "platform-tools" / "adb.exe"
    return str(local) if local.exists() else (shutil.which("adb") or "adb")


def _shell(cmd: str) -> str:
    return subprocess.run([_adb(), "shell", cmd], capture_output=True, text=True, encoding="utf-8").stdout


def _quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def on_phone(mobile: str) -> bool:
    out = _shell(f"content query --uri content://com.android.contacts/phone_lookup/{mobile} --projection _id")
    return "Row:" in out


def add_to_phone(name: str, mobile: str) -> bool:
    """One local contact (no account), like a number saved by hand. False when it is already there."""
    if on_phone(mobile):
        return False
    _shell("content insert --uri content://com.android.contacts/raw_contacts "
           "--bind account_type:n: --bind account_name:n:")
    out = _shell("content query --uri content://com.android.contacts/raw_contacts --projection _id --sort '_id DESC'")
    raw = out.split("_id=")[1].split()[0].strip(",")
    data = "content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:" + raw
    _shell(f"{data} --bind mimetype:s:vnd.android.cursor.item/name --bind data1:s:{_quote(name)}")
    _shell(f"{data} --bind mimetype:s:vnd.android.cursor.item/phone_v2 --bind data1:s:{_quote(mobile)} --bind data2:i:2")
    return True


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data", type=Path, default=Path("data"))
    p.add_argument("--user", default=DEMO_MEENA)
    p.add_argument("--adb", action="store_true", help="add the contacts to the connected phone or emulator")
    a = p.parse_args()
    book = address_book(a.data, a.user)
    for c in book:
        note = f"paid {c['paid']}x Rs {c['paid_inr']:,.0f}" if c["paid"] else "never paid"
        if c["sent_to_user"]:
            note += f", sent the user money {c['sent_to_user']}x"
        added = ("added" if add_to_phone(c["name"], c["mobile"]) else "already on phone") if a.adb else ""
        print(f"{c['name']:<18} {c['mobile']:<15} {c['upi_id']:<26} {note:<34} {added}")


if __name__ == "__main__":
    main()
