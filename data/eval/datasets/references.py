"""Load the reference datasets in data/external/reference_datasets/ into one common shape.

Every loader returns a Ref: `tx` with the common columns below, plus `raw`, the dataset's own
columns (used only for the label-leakage test), and some facts about the source.

Common columns of `tx`:
    ts        datetime64 (naive, local time of the source)
    user      payer id, or NA when the dataset has none
    payee     payee id, or NA
    amount    float, in the dataset's own currency
    kind      'P2P' | 'P2M' | 'BILL' | 'RECHARGE' | NA when unknown
    bank      payer bank name, or NA
    label     0/1 (fraud, suspicious or laundering, whatever the source calls it)

Big sets (SAML-D, AMLworld, PaySim) are cut to their first `max_rows` rows in time order, so
per-user history inside the window stays complete.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.csv as pacsv

ROOT = Path(__file__).resolve().parents[2] / "external" / "reference_datasets"
MAX_ROWS = 2_000_000


@dataclass
class Ref:
    name: str
    tx: pd.DataFrame
    raw: pd.DataFrame
    currency: str
    is_upi: bool
    label_kind: str
    real: bool
    notes: list[str] = field(default_factory=list)


def _common(ts, user, payee, amount, kind, bank, label) -> pd.DataFrame:
    n = len(amount)
    na = pd.Series([pd.NA] * n, dtype="string")
    def s(x):
        return na if x is None else pd.Series(np.asarray(x), dtype="string")
    tx = pd.DataFrame({
        "ts": pd.to_datetime(np.asarray(ts)),
        "user": s(user), "payee": s(payee),
        "amount": np.asarray(amount, dtype=float),
        "kind": s(kind), "bank": s(bank),
        "label": np.asarray(label, dtype=int),
    })
    return tx.sort_values("ts", kind="stable").reset_index(drop=True)


def _csv(path: Path, max_rows: int | None = None) -> pd.DataFrame:
    df = pacsv.read_csv(path).to_pandas()
    return df.head(max_rows) if max_rows else df


def skullagos() -> Ref:
    d = _csv(ROOT / "kaggle_upi/upi_transactions_2024.csv")
    kind = d["transaction type"].map({"P2P": "P2P", "P2M": "P2M", "Bill Payment": "BILL",
                                      "Recharge": "RECHARGE"})
    tx = _common(d["timestamp"], None, None, d["amount (INR)"], kind, d["sender_bank"], d["fraud_flag"])
    raw = d.drop(columns=["transaction id", "timestamp", "fraud_flag"])
    return Ref("skullagos_upi_2024", tx, raw.loc[d["timestamp"].argsort()].reset_index(drop=True),
               "INR", True, "fraud_flag", False,
               ["No payer or payee ids, so no per-user history."])


def belbino() -> Ref:
    d = _csv(ROOT / "kaggle_upi/indian_banking_transactions.csv")
    d = d[(d.transaction_type == "UPI") & (d.transaction_direction == "Debit")].reset_index(drop=True)
    ts = pd.to_datetime(d.transaction_date.astype(str) + " " + d.transaction_time.astype(str))
    kind = np.where(d.merchant_category == "Peer Transfer", "P2P", "P2M")
    order = np.argsort(ts.values, kind="stable")
    tx = _common(ts, d.customer_id, None, d.transaction_amount, kind, None, d.is_fraud)
    raw = d.drop(columns=["transaction_id", "customer_id", "transaction_date", "transaction_time",
                          "is_fraud"]).iloc[order].reset_index(drop=True)
    return Ref("belbino_banking_upi", tx, raw, "INR", True, "is_fraud", False,
               ["UPI debits only (of 550k mixed-channel rows).",
                "P2P/P2M inferred: merchant_category 'Peer Transfer' = P2P."])


def razorpay() -> Ref:
    d = _csv(ROOT / "kaggle_upi/fraud_data_20251225_004640.csv")
    d = d[d.status == "success"].reset_index(drop=True)
    order = np.argsort(pd.to_datetime(d.timestamp).values, kind="stable")
    tx = _common(d.timestamp, d.device_fingerprint, None, d.amount, None, d.bank,
                 d.is_suspicious.astype(int))
    # agent_type / fraud_score / fraud_reasons are the generator's own answer key, not features
    raw = d.drop(columns=["id", "razorpay_payment_id", "timestamp", "is_suspicious", "agent_type",
                          "fraud_score", "fraud_reasons", "ip_address", "device_fingerprint",
                          "error_code", "status"]).iloc[order].reset_index(drop=True)
    return Ref("razorpay_upi_sim", tx, raw, "INR", True, "is_suspicious (rule score)", False,
               ["Successful payments only. Label is the generator's own rule score, not fraud.",
                "Payer = device fingerprint (no user id)."])


def saml_d(max_rows: int = MAX_ROWS) -> Ref:
    d = _csv(ROOT / "kaggle_upi/SAML-D.csv", max_rows)
    ts = pd.to_datetime(d.Date.astype(str) + " " + d.Time.astype(str))
    tx = _common(ts, d.Sender_account, d.Receiver_account, d.Amount, None, None, d.Is_laundering)
    raw = d.drop(columns=["Time", "Date", "Sender_account", "Receiver_account", "Is_laundering",
                          "Laundering_type"]).iloc[np.argsort(ts.values, kind="stable")]
    return Ref("saml_d", tx, raw.reset_index(drop=True), "GBP", False, "Is_laundering", False,
               [f"First {len(d):,} rows. Laundering_type is the answer key and is dropped."])


def amlworld(max_rows: int = MAX_ROWS) -> Ref:
    d = pacsv.read_csv(ROOT / "aml/HI-Small_Trans.csv").to_pandas().head(max_rows)
    d.columns = ["ts", "from_bank", "from_acct", "to_bank", "to_acct", "amount_received",
                 "recv_currency", "amount_paid", "pay_currency", "format", "label"]
    ts = pd.to_datetime(d.ts, format="%Y/%m/%d %H:%M")
    tx = _common(ts, d.from_acct, d.to_acct, d.amount_paid, None, d.from_bank.astype(str), d.label)
    raw = d.drop(columns=["ts", "from_acct", "to_acct", "label"]).iloc[np.argsort(ts.values, kind="stable")]
    return Ref("ibm_amlworld_hi_small", tx, raw.reset_index(drop=True), "mixed (mostly USD)", False,
               "Is Laundering", False, [f"First {len(d):,} rows of 5.08M."])


def paysim(max_rows: int = MAX_ROWS) -> Ref:
    d = pd.read_parquet(ROOT / "real_world/paysim/paysim_mobile_money_synthetic.parquet")
    d = d.sort_values("ts", kind="stable").head(max_rows).reset_index(drop=True)
    ts = pd.to_datetime(d.ts, unit="h")  # PaySim 'step': one per simulated hour
    kind = np.where(d["type"].isin(["PAYMENT"]), "P2M", "P2P")
    tx = _common(ts, d.user_id, d.nameDest, d.amount, kind, None, d.label)
    raw = d[["type", "amount", "seen_user"]].copy()
    return Ref("paysim", tx, raw, "generic (mobile money)", False, "isFraud", False,
               [f"First {len(d):,} rows in time order. Balance columns were removed earlier (they leak the label).",
                "PAYMENT treated as P2M, other types as P2P."])


def xente() -> Ref:
    d = pd.read_parquet(ROOT / "real_world/xente/xente_mobile_money_uganda_real.parquet")
    d = d.sort_values("ts", kind="stable").reset_index(drop=True)
    ts = d.ts.dt.tz_convert("Africa/Kampala").dt.tz_localize(None)
    tx = _common(ts, d.user_id, d.ProviderId, d.Value, None, None, d.label)
    raw = d[["ProviderId", "ProductId", "ProductCategory", "ChannelId", "PricingStrategy", "Value"]].copy()
    return Ref("xente_real", tx, raw, "UGX", False, "FraudResult", True,
               ["Real transactions (Uganda, Nov 2018 to Feb 2019). Payee = provider."])


LOADERS = {"skullagos_upi_2024": skullagos, "belbino_banking_upi": belbino,
           "razorpay_upi_sim": razorpay, "saml_d": saml_d, "ibm_amlworld_hi_small": amlworld,
           "paysim": paysim, "xente_real": xente}


def load_all(names=None) -> dict[str, Ref]:
    return {n: LOADERS[n]() for n in (names or LOADERS)}


# NPCI bank names -> the short names the datasets use
_BANK_ALIASES = {"YES BANK": "Yes Bank", "STATE BANK OF INDIA": "SBI", "AXIS": "Axis", "HDFC": "HDFC",
                 "ICICI": "ICICI", "KOTAK": "Kotak", "PUNJAB NATIONAL": "PNB", "BANK OF BARODA": "BOB",
                 "CANARA": "Canara", "INDUSIND": "IndusInd", "UNION BANK": "Union"}


def npci_bank_shares() -> pd.Series:
    """Share of September 2026 UPI volume by beneficiary bank, from the NPCI workbook."""
    x = pd.read_excel(ROOT / "npci/Ecosystem-Statistics-UPI-Chargeback-2026-Sep.xlsx", header=0)
    x.columns = ["sr", "code", "bank", "txns", "cb_ratio", "cb_recv", "cb_acc", "repres"]
    x = x[pd.to_numeric(x.txns, errors="coerce").notna()]
    def short(name: str) -> str:
        up = str(name).upper()
        return next((v for k, v in _BANK_ALIASES.items() if k in up), "Other")
    s = x.assign(short=x.bank.map(short), txns=x.txns.astype(float)).groupby("short").txns.sum()
    return (s / s.sum()).sort_values(ascending=False)
