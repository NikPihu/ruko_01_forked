"""Bank UPI alert parser, the same rules as the phone's `BankSms` (android signals/MoneyFlow.kt).

Used to run the shared episode test vectors on both sides. The engine itself never sees SMS:
the phone parses alerts and sends only counts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_I = re.IGNORECASE
AMOUNT = re.compile(r"(?:\b(?:rs\.?|inr)|₹)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", _I)
AMOUNT_AFTER_VERB = re.compile(r"(?:debited|credited)\s+(?:by|with|for)\s+([0-9][0-9,]*(?:\.[0-9]{1,2})?)", _I)
VPA = re.compile(r"[a-z0-9][a-z0-9._-]{1,63}@[a-z]{2,20}", _I)
CREDIT = re.compile(r"\b(credited|received|deposited)\b", _I)
DEBIT = re.compile(r"\b(debited|sent|paid|transferred|withdrawn)\b", _I)
BANK_WORDS = re.compile(r"\b(a/c|acct|account|upi|vpa|imps|bank)\b", _I)
# Not money that moved: OTPs, requests, future debits, promotions.
SKIP = re.compile(r"\b(otp|will be debited|requested|request from|collect request|is due|offer|cashback"
                  r"|refund|reversal|reversed|interest)\b", _I)


@dataclass(frozen=True)
class Txn:
    ts: float                      # epoch seconds
    amount: float
    flow: str                      # "in" | "out"
    counterparty: Optional[str] = None
    from_sms: bool = False


def parse(body: str, ts: float) -> Optional[Txn]:
    if not BANK_WORDS.search(body) or SKIP.search(body):
        return None
    credit, debit = CREDIT.search(body), DEBIT.search(body)
    if credit and (debit is None or credit.start() < debit.start()):
        flow = "in"
    elif debit:
        flow = "out"
    else:
        return None
    m = AMOUNT.search(body) or AMOUNT_AFTER_VERB.search(body)
    if not m:
        return None
    try:
        amount = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    if amount <= 0:
        return None
    vpa = VPA.search(body)
    return Txn(ts, amount, flow, vpa.group(0).lower() if vpa else None, from_sms=True)


def trusted_sender(address: Optional[str], allow_numbers: bool = False) -> bool:
    """Banks send from registered sender IDs ("AX-HDFCBK"), never from a phone number."""
    a = (address or "").strip()
    return bool(a) and (allow_numbers or any(c.isalpha() for c in a))
