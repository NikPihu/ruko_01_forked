"""Feature builders for the blue-team tests (a unique module name: ml/tests has its own conftest)."""
from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
for p in ("backend", "ml", "data", "red_team_blue_team"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from features.build import FAMILY  # noqa: E402


T0 = datetime(2026, 10, 1, 10, tzinfo=timezone.utc)


def features(**kw) -> dict:
    f = dict.fromkeys(FAMILY)
    f.update(amount_inr=500.0, first_time_payee=False, entry_typed=False, payee_holder_type="merchant",
             payee_verified_merchant=True, payee_in_run=False, attempts_72h=0, episode_state=0, stage=0,
             entry_method="qr", payer_says=None)
    f.update(kw)
    return f


def relative_call(r: random.Random) -> dict:
    return features(on_call=True, voip_call=r.random() < 0.7, caller_unknown=None, entry_typed=True, entry_method="typed",
                    payer_says="family" if r.random() < 0.9 else None, amount_inr=r.uniform(15000, 60000),
                    first_time_payee=True, payee_holder_type="person", payee_verified_merchant=False,
                    session_hesitation=r.random() < 0.6)   # not dictated: else digital_arrest names it


def real_digital_arrest(r: random.Random) -> dict:
    return features(on_call=True, voip_call=True, caller_unknown=None, remote_control=True, session_dictated=True,
                    entry_typed=True, entry_method="typed", payer_says="government", amount_inr=r.uniform(60000, 95000),
                    first_time_payee=True, payee_holder_type="person", payee_verified_merchant=False,
                    story_mismatch=r.random() < 0.7)


def voice_clone_named_arrest(r: random.Random) -> dict:
    """A 'son in trouble' call: RUKO names it digital_arrest (unknown VoIP caller + dictated amount)."""
    return features(on_call=True, voip_call=True, caller_unknown=None, session_dictated=True, entry_typed=True,
                    entry_method="typed", payer_says="family", amount_inr=r.uniform(15000, 40000), first_time_payee=True,
                    payee_holder_type="person", payee_verified_merchant=False, session_hesitation=r.random() < 0.7,
                    payee_in_contacts=False)


def marketplace_qr(r: random.Random) -> dict:
    return features(entry_method="qr", amount_inr=r.uniform(100, 900), first_time_payee=True, payee_holder_type="person",
                    payee_verified_merchant=False, payee_pass_through_24h=1.0 if r.random() < 0.8 else 0.0,
                    attempts_72h=r.choice([2, 3]), session_abandoned_30m=1.0 if r.random() < 0.5 else 0.0)


def known_trading(r: random.Random) -> dict:
    return features(lure_tag="trading_tip", lure_max_conf_72h=0.8, entry_typed=True, entry_method="typed",
                    payer_says="investment", amount_inr=r.uniform(5000, 20000), first_time_payee=True,
                    payee_holder_type="person", payee_verified_merchant=False)
