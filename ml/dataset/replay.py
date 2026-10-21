"""Point-in-time replay: a simulated world -> one training row per payment by an app user.

Each payment becomes the request the phone would have sent (phone_view.py). It goes through the
same stage tracker, intel lookups and build_features() as the live engine (backend/api/main.py),
using only what existed at that moment:
- the payer's history before the payment (the live engine's Baselines read the whole ledger,
  including the payment itself; fine at the demo clock, a label leak for training);
- payee features, MuleHunter, registry and FRI as of the payment (the mock services' own code,
  called directly with the store's clock set to the payment time);
- the tracker sees every earlier payment, including those not kept as rows.
Device-only features (never sent) are added with the `dev_` prefix.

    PYTHONPATH=backend;ml;data python -m dataset.replay --data ml/data/worlds/dev --out ml/data/tables/dev.parquet
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from types import SimpleNamespace

import pandas as pd
from fastapi import HTTPException

from api.intel import NUMBER_UPI, IntelResult
from dataset.device_features import device_features
from dataset.phone_view import DAY, PhoneView, epoch_seconds, keyed_rng, load_assumptions
from features.build import build_features
from features.tracker import StageTracker
from features.user_baseline import UserBaseline
from intel_mock import bank, dot_fri, i4c_registry, npci
from intel_mock.store import Store
from schema.events import DecideRequest

TABLES = ("users", "accounts", "ledger", "context_events", "journeys")
STATUS = {404: "not_found", 403: "not_shared"}  # same mapping as api.intel.IntelAdapter._get


def load_world(data_dir: str | Path) -> tuple[dict[str, pd.DataFrame], dict]:
    d = Path(data_dir)
    tables = {name: pd.read_parquet(d / f"{name}.parquet") for name in TABLES}
    return tables, json.loads((d / "manifest.json").read_text())


class IntelReplay:
    """api.intel.IntelAdapter without HTTP: the mock routers' own functions at a chosen moment."""

    def __init__(self, store: Store):
        self.store = store
        # The routers only read request.app.state.store and .mulehunter_cache.
        self.request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(store=store, mulehunter_cache={})))

    @staticmethod
    def _call(fn, *args, **kwargs) -> tuple[str, dict | None]:
        try:
            return "ok", fn(*args, **kwargs)
        except HTTPException as e:
            return STATUS.get(e.status_code, "error"), None

    def lookup(self, payee_upi: str, caller_number: str | None, at: datetime) -> IntelResult:
        self.store.now = at  # every mock reads its clock from the store
        upi = payee_upi.strip().lower()
        res, req = IntelResult(), self.request
        calls = {"npci": self._call(npci.resolve, upi, req)}
        status, body = calls["npci"]
        calls["bank"] = (self._call(bank.payee_risk, body["bank_code"], body["upi_id"], req) if status == "ok"
                         else ("skipped", None))
        calls["payee_registry"] = self._call(i4c_registry.registry, req, upi_id=upi)
        m = NUMBER_UPI.match(upi)
        if m:
            calls["payee_fri"] = self._call(dot_fri.fri, "+91" + m.group(1), req)
        if caller_number:
            calls["caller_registry"] = self._call(i4c_registry.registry, req, mobile=caller_number)
            calls["caller_fri"] = self._call(dot_fri.fri, caller_number, req)
        for name, (status, body) in calls.items():
            res.status[name] = status
            setattr(res, name, body)
        return res


class EngineReplay:
    """The engine's decide path up to the scorer: tracker -> intel -> build_features."""

    def __init__(self, store: Store):
        self.tracker = StageTracker()
        self.intel = IntelReplay(store)

    def step(self, req: DecideRequest, base: UserBaseline, trusted: bool = False, with_features: bool = True):
        upi = req.payee_upi_id.strip().lower()
        state = self.tracker.update(req, new_payee=upi not in base.known_payees and not trusted)
        if not with_features:
            return state, None, None
        call = req.context.call if req.context else None
        res = self.intel.lookup(upi, call.caller_number if call else None, req.ts)
        return state, res, build_features(req, state, res, base, trusted)


def bank_baseline(view: PhoneView, uid: str, t: float) -> UserBaseline:
    """features.user_baseline.UserBaseline, but only from payments before `t` (90 days)."""
    h = view.own_history(uid, t)
    if not h["payees"]:
        return UserBaseline()
    amounts = h["amounts"]
    return UserBaseline(max_90d=max(amounts) if amounts else None,
                        median_90d=median(amounts) if amounts else None, known_payees=h["payees"])


def replay(data_dir: str | Path, sample_normal: float = 0.25, warmup_days: float = 14, seed: int = 0,
           assumptions: dict | None = None, users: list[str] | None = None, log_every: int = 0) -> pd.DataFrame:
    """One row per kept payment. Scam payments are always kept; normal ones with probability
    `sample_normal` and weight 1/sample_normal. The first `warmup_days` build history only."""
    tables, manifest = load_world(data_dir)
    a = assumptions or load_assumptions()
    view = PhoneView(tables, a, seed)
    engine = EngineReplay(Store.load(data_dir))
    start = datetime.fromisoformat(manifest["config"]["end"]) - timedelta(days=manifest["config"]["n_days"])
    keep_from = (start + timedelta(days=warmup_days)).timestamp()

    u = tables["users"]
    upi_user = dict(zip(u.upi_id, u.user_id))
    audit = {uid: (age, lang, region) for uid, age, lang, region in zip(u.user_id, u.age_band, u.language, u.region)}
    acc = tables["accounts"].set_index("upi_id")
    playbook = dict(zip(tables["journeys"].journey_id, tables["journeys"].playbook))
    led = tables["ledger"]
    led = led[led.from_upi.isin(upi_user)].sort_values("ts", kind="stable")
    if users is not None:
        led = led[led.from_upi.map(upi_user).isin(set(users))]

    rows, t0 = [], time.perf_counter()
    journey_paid: dict[str, int] = {}  # scam payments so far per journey, kept or not
    cols = zip(led.tx_id.tolist(), led.ts.tolist(), epoch_seconds(led.ts), led.from_upi.tolist(),
               led.to_upi.tolist(), led.amount.tolist(), led.entry_method.tolist(), led.flow.tolist(),
               led.journey_id.tolist(), led.label_is_scam.tolist(), led.label_stage.tolist())
    for n, (tx, ts, t, frm, to, amount, entry, flow, jid, is_scam, stage) in enumerate(cols, 1):
        uid = upi_user[frm]
        is_scam = bool(is_scam)
        jid = jid if isinstance(jid, str) else None
        pb = playbook.get(jid) if jid else None
        pay_index = None
        if is_scam and jid:
            pay_index = journey_paid.get(jid, 0)  # 0 = the journey's first scam payment
            journey_paid[jid] = pay_index + 1
        rng = keyed_rng(seed, "payment", tx)
        keep = t >= keep_from and (is_scam or rng.random() < sample_normal)
        base = bank_baseline(view, uid, t)
        ctx, raw = view.context_at(uid, t)
        says = view.payer_says(rng, entry, amount, is_scam, pb, to)
        req = DecideRequest(request_id=tx, user_id=uid, payee_upi_id=to, amount_inr=float(amount),
                            entry_method=entry, payer_says=says, ts=ts.to_pydatetime(), context=ctx)
        state, res, feats = engine.step(req, base, with_features=keep)
        if keep:
            hist = view.own_history(uid, t)
            first = to not in hist["payees"]
            sess = view.session(rng, uid, entry, is_scam, pb, first)
            tr = view.traits[uid]
            age, lang, region = audit[uid]
            payee = acc.loc[to] if to in acc.index else None
            rows.append({
                "tx_id": tx, "ts": ts, "user_id": uid, "payee_upi": to, "amount": float(amount),
                "entry_method": entry, "flow": flow, "journey_id": jid, "playbook": pb,
                "label_is_scam": is_scam, "label_stage": stage if isinstance(stage, str) else None,
                "journey_pay_index": pay_index, "weight": 1.0 if is_scam else 1.0 / sample_normal,
                "payer_says": says, "has_context": ctx is not None,  # the tracker stage is feature `stage`
                "consent_call": tr.call_signals, "consent_app": tr.app_checks, "consent_sms": tr.sms,
                "android_15": tr.android_15, "coached": sess["coached"],
                "intel_status": json.dumps(res.status, sort_keys=True),
                # Audit only: never model inputs.
                "audit_age_band": age, "audit_language": lang, "audit_region": region,
                "payee_is_mule": None if payee is None else bool(payee["is_mule"]),
                "payee_mule_kind": None if payee is None else payee["mule_kind"],
                "payee_merchant_kind": None if payee is None else payee["merchant_kind"],
                **feats,
                **device_features(raw, hist, float(amount), entry, to, t, sess, tr.any_shield,
                                  a["phone"]["escalation_factor"]),
            })
        if log_every and n % log_every == 0:
            print(f"  {n:,}/{len(led):,} payments, {len(rows):,} rows, {time.perf_counter() - t0:.0f}s", flush=True)
    return pd.DataFrame(rows)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data", required=True, type=Path, help="a world folder written by sim.generate")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--sample-normal", type=float, default=0.25)
    p.add_argument("--warmup-days", type=float, default=14)
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args()
    t0 = time.perf_counter()
    df = replay(a.data, a.sample_normal, a.warmup_days, a.seed, log_every=50_000)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(a.out, index=False)
    scam = df[df.label_is_scam]
    print(f"{len(df):,} rows ({len(scam):,} scam payments, {scam.journey_id.nunique()} journeys) "
          f"in {time.perf_counter() - t0:.0f}s -> {a.out}")


if __name__ == "__main__":
    main()
