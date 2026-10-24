"""Test cases for the phone's step code: device features in, steps out -> contracts/examples/steps_vectors.json

    PYTHONPATH=backend;ml;data python -m model.device.steps_vectors

Every real payment in artifacts/v0/device_feature_vectors.json (run model.device.feature_vectors first),
plus edge cases the simulated world rarely shows (a WhatsApp call, the cool-off, switches off).
android/.../signals/StepsTest.kt must give the same steps with features/steps.py phone_steps.
"""
from __future__ import annotations

import json
from pathlib import Path

from features.steps import phone_steps

ROOT = Path(__file__).resolve().parents[3]
FEATURE_VECTORS = Path(__file__).resolve().parents[1] / "artifacts" / "v0" / "device_feature_vectors.json"
OUT = ROOT / "contracts" / "examples" / "steps_vectors.json"

QUIET = {"dev_call_active": 0.0, "dev_remote_installed": 0.0, "dev_screen_recorded": 0.0, "dev_accessibility": 0.0,
         "dev_sideloaded_24h": 0.0, "dev_lure_max": 0.0, "dev_lure_arrest": 0.0, "dev_lure_kyc": 0.0,
         "dev_lure_task": 0.0, "dev_lure_trading": 0.0, "dev_lure_refund": 0.0, "dev_ep_state": 0.0,
         "dev_ep_bait_credits": 0.0, "dev_ep_escalation": 0.0, "dev_first_time_payee": 0.0}
EDGE = {
    "nothing_measured": {},
    "quiet_payment": QUIET,
    "whatsapp_call_now": {**QUIET, "dev_call_active": 1.0, "dev_call_voip": 1.0, "dev_call_minutes": 38.0,
                          "dev_call_incoming": 1.0, "dev_first_time_payee": 1.0},
    "called_unknown_number": {**QUIET, "dev_call_active": 1.0, "dev_call_unknown": 1.0, "dev_call_incoming": 0.0,
                              "dev_call_minutes": 3.0, "dev_screen_recorded": 1.0},
    "cool_off_after_call": {**QUIET, "dev_call_voip": 1.0, "dev_call_ended_min_ago": 42.25},
    "call_ended_too_long_ago": {**QUIET, "dev_call_unknown": 1.0, "dev_call_ended_min_ago": 400.0},
    "remote_app_installed_recently": {**QUIET, "dev_remote_installed": 1.0, "dev_remote_min_ago": 119.95},
    "lures_on_the_bar": {**QUIET, "dev_lure_arrest": 0.6, "dev_lure_kyc": 0.5999, "dev_lure_min_ago": 7.05,
                         "dev_lure_other_scam": 0.92, "dev_lure_unclear": 1.0},
    "task_episode_active": {**QUIET, "dev_ep_state": 2.0, "dev_ep_bait_credits": 3.0, "dev_ep_escalation": 2.0},
    "coached_session": {**QUIET, "dev_sess_digits": 6.0, "dev_sess_median_gap_s": 2.5, "dev_sess_max_gap_s": 5.0,
                        "dev_sess_pasted": 1.0, "dev_sess_paste_after_return_s": 20.0, "dev_sess_app_switches": 2.0,
                        "dev_sess_pay_screen_s": 180.0, "dev_sess_abandoned_30m": 0.0},
    "pasted_without_leaving": {**QUIET, "dev_sess_pasted": 1.0, "dev_sess_app_switches": 0.0, "dev_sess_digits": 3.0},
    "big_payment_for_this_user": {**QUIET, "dev_amount_to_max": 1.5, "dev_first_time_payee": 1.0},
}


def case(name: str, features: dict) -> dict:
    return {"case": name, "features": features,
            "steps": {k: [seen, ago] for k, (seen, ago) in phone_steps(features).items()}}


def main() -> None:
    cases = [case(name, f) for name, f in EDGE.items()]
    data = json.loads(FEATURE_VECTORS.read_text(encoding="utf-8"))
    for v in data["vectors"]:
        if v["features"] is not None and any(x is not None for x in v["features"].values()):
            cases.append(case(v["case"], v["features"]))
    OUT.write_text(json.dumps({"version": "steps-0.1", "about": __doc__.splitlines()[0], "cases": cases}, indent=1),
                   encoding="utf-8")
    print(f"{len(cases)} cases -> {OUT}")


if __name__ == "__main__":
    main()
