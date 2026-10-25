"""model.steps_table: a replay table row gives the same steps as the engine's two readings merged."""
import math

import pandas as pd

from features.steps import STEP_IDS
from model.steps_table import row_steps, table_steps


def row(**kw):
    base = {"has_context": True, "consent_sms": True, "lure_tag": "kyc", "lure_max_conf_72h": 0.8,
            "entry_method": "qr", "on_call": True, "caller_unknown": True, "voip_call": False,
            "first_time_payee": True, "amount_inr": 500.0, "dev_call_active": 1.0, "dev_remote_installed": 1.0,
            "dev_remote_min_ago": 10.0}
    return {**base, **kw}


def test_row_steps_merges_server_and_phone():
    s = row_steps(row())
    assert s["lure:kyc"] is True and s["lure:refund"] is False and s["qr_entry"] is True
    assert s["unknown_call"] is True and s["remote_control"] is True and s["amount_small"] is True


def test_no_sms_consent_leaves_the_lures_unknown_not_absent():
    s = row_steps(row(consent_sms=False, lure_tag=float("nan")))
    assert s["lure:kyc"] is None and s["lure:trading_tip"] is None


def test_table_columns_are_the_vocabulary_with_nan_for_unknown():
    t = table_steps(pd.DataFrame([row(), row(consent_sms=False)]))
    assert list(t.columns) == list(STEP_IDS)
    assert t.loc[0, "lure:kyc"] == 1.0 and math.isnan(t.loc[1, "lure:kyc"])
