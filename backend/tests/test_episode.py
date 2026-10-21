"""The shared episode vectors (contracts/examples/episode_vectors.json) must pass here and on the phone."""
import json
from datetime import datetime
from pathlib import Path

import pytest

from features import bank_sms
from features.episode import EpisodeTracker, escalation_steps, load_rules

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "examples" / "episode_vectors.json")
                     .read_text(encoding="utf-8"))
BASE = datetime.fromisoformat(VECTORS["base_ts"]).timestamp()
FLOAT_FIELDS = {"age_days", "out_to_in_ratio"}


def run(v: dict) -> dict:
    tr = EpisodeTracker(load_rules(), sms_read=v["sms_read"])
    for e in sorted(v["events"], key=lambda e: e["at_h"]):
        ts = BASE + e["at_h"] * 3600
        if "sms" in e:
            # The vectors use release rules: a numbered sender is never a bank.
            if bank_sms.trusted_sender(e["sms"]["from"]):
                t = bank_sms.parse(e["sms"]["body"], ts)
                if t:
                    tr.add(t)
        elif "app" in e:
            tr.add(bank_sms.Txn(ts, float(e["app"]["amount"]), "out", e["app"]["to"].lower()))
        elif e.get("dismiss"):
            tr.dismiss(ts)
    return tr.summary(BASE + v["now_h"] * 3600, payee=v.get("payee"))


def test_rules_version_matches():
    assert load_rules()["version"] == VECTORS["rules_version"]


@pytest.mark.parametrize("v", VECTORS["vectors"], ids=[v["name"] for v in VECTORS["vectors"]])
def test_vector(v):
    got = run(v)
    for k, want in v["expect"].items():
        if k in FLOAT_FIELDS and want is not None:
            assert got[k] == pytest.approx(want, abs=0.01), k
        else:
            assert got[k] == want, k


def test_escalation_counts_only_the_latest_run():
    assert escalation_steps([]) == 0
    assert escalation_steps([1500, 3000, 6500]) == 2
    assert escalation_steps([5000, 1000, 2000]) == 1
    assert escalation_steps([1000, 1200]) == 0
