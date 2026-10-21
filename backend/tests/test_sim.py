import pandas as pd
import pytest

from sim.accounts import DEMO_KIRANA_UPI, DEMO_MEENA, DEMO_MULE_UPI
from sim.config import HANDLES, P2P_TXN_CAP, SimConfig
from sim.generate import build_world

CFG = SimConfig(seed=1, n_users=400, n_days=20, scam_rate=0.05)


@pytest.fixture(scope="module")
def t():
    return build_world(CFG)


def _payee_stats(led: pd.DataFrame, upi: str) -> tuple[float, float]:
    inflow, outflow = led[led.to_upi == upi], led[led.from_upi == upi]
    # A repeat payer comes back on a different day; split tranches in one sitting don't count.
    days = inflow.assign(d=inflow.ts.dt.date).groupby("from_upi").d.nunique()
    repeat = (days > 1).sum() / max(len(days), 1)
    pass_through = outflow.amount.sum() / max(inflow.amount.sum(), 1)
    return repeat, pass_through


def test_same_seed_same_world(t):
    again = build_world(CFG)
    for name in t:
        pd.testing.assert_frame_equal(t[name], again[name])


def test_identifiers_unique_and_resolvable(t):
    acc = t["accounts"]
    assert acc.upi_id.is_unique and acc.mobile.is_unique and acc.account_id.is_unique
    assert set(acc.handle) <= {h.handle for h in HANDLES}
    assert (acc.upi_id.str.split("@").str[1] == acc.handle).all()
    known = set(acc.upi_id)
    assert set(t["ledger"].from_upi) <= known and set(t["ledger"].to_upi) <= known
    assert set(t["users"].upi_id) <= known


def test_account_ids_do_not_leak_labels(t):
    acc = t["accounts"]
    assert acc.account_id.str.startswith("a_").all()
    mule_ids = acc.loc[acc.is_mule, "account_id"].str[2:].astype(int)
    assert mule_ids.min() < len(acc) * 0.5  # mules are shuffled, not appended at the end


def test_timestamps_inside_window(t):
    for name in ("ledger", "context_events"):
        ts = t[name].ts
        assert ts.max() <= CFG.end and ts.min() >= CFG.start - pd.Timedelta(days=1)
        assert str(ts.dt.tz) in ("UTC+05:30", "+05:30")


def test_p2p_cap_respected(t):
    scam = t["ledger"][t["ledger"].label_is_scam]
    assert (scam.amount <= P2P_TXN_CAP).all()


def test_scam_payments_have_stages(t):
    led = t["ledger"]
    in_app = led[led.flow == "scam"]
    assert len(in_app) > 0
    assert set(in_app.label_stage) <= {"S4", "S5"}
    assert in_app.journey_id.notna().all()
    assert (led.loc[led.flow == "normal", "label_is_scam"] == False).all()  # noqa: E712


def test_kirana_vs_mule_signals(t):
    led, acc = t["ledger"], t["accounts"]
    k_repeat, k_pass = _payee_stats(led, DEMO_KIRANA_UPI)
    assert k_repeat > 0.7 and k_pass == 0
    mules = acc[acc.is_mule & (acc.mule_kind != "cash_out")]
    stats = [(k, *_payee_stats(led, u)) for k, u in zip(mules.mule_kind, mules.upi_id)]
    active = [(k, r, p) for k, r, p in stats if p > 0]
    assert active, "some mules should have received and forwarded money"
    # Warm-up mules are groomed by the same feeders daily, so they look like they have
    # regulars -- that disguise is the point. Only pass-through gives them away.
    assert all(r < 0.4 for k, r, _ in active if k != "warm_up")
    assert all(p > 0.6 for _, _, p in active)


def test_lists_learn_only_from_reports(t):
    rep, j, acc = t["reports"], t["journeys"], t["accounts"]
    assert (rep.listed_at > rep.filed_at).all()
    # Every report that names a journey points at that journey's real mule or caller.
    linked = rep[rep.journey_id.notna()].merge(j, on="journey_id")
    ok = linked.apply(lambda r: r.identifier in r.mule_upi_ids.split(",") or r.identifier == r.caller_number, axis=1)
    assert ok.all()
    assert (linked.filed_at >= linked.last_payment_at).all()
    # False reports only ever hit honest accounts.
    false_ids = set(rep.loc[rep.is_false, "identifier"])
    assert false_ids and not (false_ids & set(acc.loc[acc.is_mule, "upi_id"]))


def test_report_rate_roughly_as_configured(t):
    j = t["journeys"]
    real = j[(j.n_payments > 0) & ~j.is_demo]
    assert 0.2 <= real.reported.mean() <= 0.8


def test_demo_actors(t):
    users, acc, rep, led = t["users"], t["accounts"], t["reports"], t["ledger"]
    assert DEMO_MEENA in set(users.user_id)
    meena = users.set_index("user_id").loc[DEMO_MEENA]
    assert meena.age_band == "60+" and meena.region == "Pune"
    # Meena's scam is the live demo, so her history is clean.
    assert not led[(led.from_upi == meena.upi_id) & led.label_is_scam].shape[0]
    mule = acc.set_index("upi_id").loc[DEMO_MULE_UPI]
    assert mule.is_mule and mule.partner_bank
    assert (CFG.end - mule.created_at).days <= 5
    assert DEMO_MULE_UPI not in set(rep.identifier)  # the fresh-mule gap
    assert led[(led.to_upi == DEMO_MULE_UPI) & led.label_is_scam].shape[0] > 0
    assert DEMO_KIRANA_UPI not in set(rep.identifier)


# ---------- Pay-screen sessions (c2-0.5) ----------

def test_sessions_leave_the_rest_of_the_world_unchanged(t, monkeypatch):
    import sim.generate as gen
    monkeypatch.setattr(gen, "build_sessions", lambda w: None)
    without = build_world(CFG)
    ev = t["context_events"]
    pd.testing.assert_frame_equal(t["ledger"], without["ledger"])
    pd.testing.assert_frame_equal(ev[ev.event_type != "pay_session"].reset_index(drop=True),
                                  without["context_events"])


def test_every_user_payment_has_one_session(t):
    import json
    users = set(t["users"].upi_id)
    paid = t["ledger"][t["ledger"].from_upi.isin(users)]
    ses = t["context_events"][t["context_events"].event_type == "pay_session"]
    assert len(ses) == len(paid)
    s = json.loads(ses["attrs"].iloc[0])
    assert set(s) == {"amount_digits", "amount_median_gap_s", "amount_max_gap_s", "amount_gap_vs_usual",
                      "amount_edits", "payee_pasted", "pasted_within_s_of_return", "app_switches",
                      "away_s", "pay_screen_s", "abandoned_flows_30m"}


def test_scam_sessions_look_coached_more_often(t):
    import json
    ses = t["context_events"][t["context_events"].event_type == "pay_session"]
    a = pd.DataFrame([json.loads(x) for x in ses["attrs"]]).assign(scam=ses.label_is_scam.values)
    slow = a.amount_gap_vs_usual.fillna(1) >= 2.5
    assert slow[a.scam].mean() > 3 * slow[~a.scam].mean()
    assert (a[a.scam].app_switches > 0).mean() > (a[~a.scam].app_switches > 0).mean()
