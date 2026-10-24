import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from intel_mock.app import create_app as create_mock
from api.main import create_app as create_engine
from sim.accounts import DEMO_KIRANA_UPI, DEMO_MEENA, DEMO_MULE_UPI
from sim.config import SimConfig
from sim.generate import build_world, write_world

CFG = SimConfig(seed=1, n_users=400, n_days=20, scam_rate=0.05)
NOW = CFG.end + timedelta(hours=10, minutes=40)
UNKNOWN_CALLER = "+919812345670"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    out = tmp_path_factory.mktemp("data")
    tables = build_world(CFG)
    write_world(tables, CFG, out)
    return out, tables


@pytest.fixture()
def mock(world):
    app = create_mock(world[0])
    return app, TestClient(app)


@pytest.fixture()
def engine(world, mock):
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock[0]), base_url="http://mock")
    app = create_engine(world[0], intel_client=client, intel_cache_ttl_s=0, log_path=None,
                        evidence_async=False)
    return TestClient(app)


def pump(mock_client, world, n=40):
    acc = world[1]["accounts"]
    payers = acc[(acc.holder_type == "person") & ~acc.is_mule].upi_id[:n]
    for p in payers:
        mock_client.post("/npci/pay", json={"from_upi": p, "to_upi": DEMO_MULE_UPI, "amount": 1500})
    cash_out = acc[acc.mule_kind == "cash_out"].upi_id.iloc[0]
    mock_client.post("/npci/pay", json={"from_upi": DEMO_MULE_UPI, "to_upi": cash_out, "amount": 54000})
    # Warm the bank's first (slowest) calculation for this payee, as a prefetch would, so the
    # functional tests don't depend on how busy the machine is. Timing tests use real budgets.
    mock_client.get(f"/banks/axis-bank/payee-risk/{DEMO_MULE_UPI}")


def req(user=DEMO_MEENA, payee=DEMO_MULE_UPI, amount=95_000, entry="typed", says=None,
        context=None, ts=NOW, rid="r_1"):
    body = {"request_id": rid, "user_id": user, "payee_upi_id": payee, "amount_inr": amount,
            "entry_method": entry, "ts": ts.isoformat(), "context": context}
    if says:
        body["payer_says"] = says
    return body


MEENA_CONTEXT = {
    "call": {"active": True, "kind": "voip", "caller_number": UNKNOWN_CALLER,
             "caller_in_contacts": False, "started_min_ago": 38},
    "device": {"remote_access_active": True, "remote_app_installed_min_ago": 25},
    "lures": [],
}


def users_in(world, region="Pune"):
    u = world[1]["users"]
    return u[(u.region == region) & (u.user_id != DEMO_MEENA)].user_id.tolist()


# ---------- the demo stories ----------

def test_meena_digital_arrest_gets_paused(engine, mock, world):
    pump(mock[1], world)
    r = engine.post("/v1/decide", json=req(context=MEENA_CONTEXT, says="government")).json()
    assert r["tier"] in ("T3", "T4")
    assert {"R1_live_unknown_call", "R2_remote_control", "R3_mule_like_payee"} <= set(r["reasons"])
    assert r["playbook"] == "digital_arrest" and r["message_key"] == f"{r['tier'].lower()}_digital_arrest"
    assert r["pause_minutes"] > 0 and r["evidence_id"]
    assert "p_scam" not in r
    ev = engine.get(f"/v1/evidence/{r['evidence_id']}").json()
    assert DEMO_MULE_UPI not in str(ev) and UNKNOWN_CALLER not in str(ev)  # only hashes stored
    assert ev["intel_status"]["payee_registry"] == "ok"


def test_kirana_purchase_is_silent(engine, world):
    user = users_in(world)[0]
    r = engine.post("/v1/decide", json=req(user=user, payee=DEMO_KIRANA_UPI, amount=180, entry="qr")).json()
    assert r["tier"] == "T0" and r["reasons"] == []


def test_split_tranches_still_caught(engine, mock, world):
    """Adaptive fraudster: 5 x 19,000 instead of 95,000, and hangs up before the payments."""
    pump(mock[1], world)
    ctx = {"call": {"active": False, "kind": "voip", "caller_number": UNKNOWN_CALLER,
                    "caller_in_contacts": False, "started_min_ago": 50, "ended_min_ago": 5},
           "device": {"remote_access_active": True}, "lures": []}
    tiers, stages = [], []
    for i in range(5):
        r = engine.post("/v1/decide", json=req(amount=19_000, context=ctx, rid=f"r_{i}",
                                                ts=NOW + timedelta(minutes=4 * i))).json()
        tiers.append(r["tier"]), stages.append(r["stage"])
    assert stages[0] == "S4" and stages[-1] == "S5"
    assert max(tiers) >= "T3"
    assert "R7_tranche_pattern" in r["reasons"] or r["tier"] >= "T2"


def test_usual_shop_after_new_payees_is_not_a_tranche(engine, world):
    """Two payments to new payees, then the usual kirana: the kirana payment is not part of the run,
    so an old scam-looking SMS alone (one family) leaves it silent."""
    users = world[1]["users"].set_index("user_id")
    user = next(u for u in users_in(world) if DEMO_KIRANA_UPI in baseline(world, u).known_payees)
    others = [users.loc[u].upi_id for u in users_in(world, "Delhi")[:2]]
    lure = {"lures": [{"tag": "arrest_threat", "conf": 0.85, "min_ago": 600}]}
    for i, payee in enumerate(others):
        engine.post("/v1/decide", json=req(user=user, payee=payee, amount=2_000, context=lure,
                                           rid=f"r_new_{i}", ts=NOW + timedelta(minutes=3 * i)))
    r = engine.post("/v1/decide", json=req(user=user, payee=DEMO_KIRANA_UPI, amount=100, entry="contact",
                                           context=lure, rid="r_kirana", ts=NOW + timedelta(minutes=9))).json()
    assert r["tier"] == "T0", r
    assert "R7_tranche_pattern" not in r["reasons"]


TASK_PAYEE = "prime.task.rewards@ybl"
ACTIVE_EPISODE = {"state": "active", "age_days": 4.2, "bait_credits": 3, "bait_inr": 450, "outs": 3,
                  "outs_inr": 9_500, "new_payees": 3, "escalation_steps": 2, "last_out_inr": 6_000,
                  "out_to_in_ratio": 21.11, "payee_seen_in_episode": False, "rules_version": "episode-0.2"}
WATCHING_EPISODE = {"state": "watching", "age_days": 0.5, "bait_credits": 2, "bait_inr": 350, "outs": 0,
                    "outs_inr": 0, "new_payees": 0, "escalation_steps": 0, "last_out_inr": None,
                    "out_to_in_ratio": 0, "rules_version": "episode-0.2"}


def baseline(world, user):
    from features.user_baseline import Baselines
    return Baselines.from_data(world[0]).get(user)


def episode_ctx(ep, lures=()):
    return {"lures": list(lures), "episode": ep}


# §6 outcome table: the episode is ONE lure-family signal; T2+ needs a second, independent family.

def test_active_episode_clean_payee_normal_amount_is_at_most_t1(engine, world):
    user = users_in(world)[0]
    amount = baseline(world, user).median_90d or 500
    r = engine.post("/v1/decide", json=req(user=user, payee=TASK_PAYEE, amount=amount,
                                           context=episode_ctx(ACTIVE_EPISODE))).json()
    assert r["tier"] in ("T0", "T1")


def test_active_episode_mule_payee_pauses(engine, mock, world):
    pump(mock[1], world)
    r = engine.post("/v1/decide", json=req(amount=14_000, says="company",
                                           context=episode_ctx(ACTIVE_EPISODE))).json()
    assert r["tier"] in ("T2", "T3", "T4") and r["playbook"] == "task_job"
    assert "R10_bait_then_pay" in r["reasons"] and "R3_mule_like_payee" in r["reasons"]
    assert r["message_key"] == f"{r['tier'].lower()}_task_job"


def test_active_episode_far_above_usual_amount_is_t2(engine, world):
    user = users_in(world)[0]
    amount = 10 * (baseline(world, user).max_90d or 5_000)
    r = engine.post("/v1/decide", json=req(user=user, payee=TASK_PAYEE, amount=amount,
                                           context=episode_ctx(ACTIVE_EPISODE))).json()
    assert r["tier"] == "T2" and r["playbook"] == "task_job"
    assert {"R10_bait_then_pay", "R4_unusual_amount"} <= set(r["reasons"])


def test_watching_alone_does_not_interrupt(engine, world):
    user = users_in(world)[0]
    r = engine.post("/v1/decide", json=req(user=user, payee=TASK_PAYEE, amount=2_000,
                                           context=episode_ctx(WATCHING_EPISODE))).json()
    assert r["tier"] in ("T0", "T1")


def test_dismissed_episode_still_alerts_on_a_listed_payee(engine, mock, world):
    rep = world[1]["reports"]
    listed = rep[(rep.identifier_type == "upi_id") & ~rep.is_false & (rep.listed_at <= CFG.end)].identifier.iloc[0]
    # Warm the mock's first (slowest) answers for this payee, as a prefetch would.
    mock[1].get(f"/i4c/registry?upi_id={listed}")
    bank = mock[1].get(f"/npci/resolve/{listed}").json().get("bank_code")
    if bank:
        mock[1].get(f"/banks/{bank}/payee-risk/{listed}")
    user = users_in(world)[0]
    ep = {**WATCHING_EPISODE, "state": "dismissed", "age_days": None}
    r = engine.post("/v1/decide", json=req(user=user, payee=listed, amount=5_000, context=episode_ctx(ep))).json()
    assert r["tier"] in ("T2", "T3", "T4") and "R10_bait_then_pay" in r["reasons"]


def test_dismissed_episode_alone_is_silent(engine, world):
    user = users_in(world)[0]
    ep = {**WATCHING_EPISODE, "state": "dismissed", "age_days": None}
    r = engine.post("/v1/decide", json=req(user=user, payee=TASK_PAYEE, amount=5_000, context=episode_ctx(ep))).json()
    assert "R10_bait_then_pay" not in r["reasons"]


def test_active_episode_names_the_playbook_over_an_old_message(engine, mock, world):
    pump(mock[1], world)
    ctx = episode_ctx(ACTIVE_EPISODE, lures=[{"tag": "arrest_threat", "conf": 0.85, "min_ago": 380}])
    r = engine.post("/v1/decide", json=req(amount=14_000, context=ctx)).json()
    assert r["playbook"] == "task_job"


def test_c2_0_2_money_group_is_gone(engine):
    """Removed in c2-0.4: an old app sending `money` gets 422 and fails open on the phone."""
    ctx = {"lures": [], "money": {"bait_credits": 3, "debits": 3}}
    assert engine.post("/v1/decide", json=req(context=ctx)).status_code == 422


def test_escalation_with_no_bait_is_not_an_episode(engine, world):
    """Paying a contractor in growing instalments: no bait, so the phone's episode stays none."""
    user = users_in(world)[0]
    ep = {"state": "none", "bait_credits": 0, "bait_inr": 0, "outs": 0, "outs_inr": 0, "new_payees": 0,
          "escalation_steps": 0, "rules_version": "episode-0.2"}
    r = engine.post("/v1/decide", json=req(user=user, payee=TASK_PAYEE, amount=14_000, context=episode_ctx(ep))).json()
    assert r["tier"] in ("T0", "T1") and "R10_bait_then_pay" not in r["reasons"]


def test_episode_without_sms_is_unknown(engine, world):
    """SMS off: bait fields are null and no episode can start, so no task alert."""
    user = users_in(world)[0]
    ep = {"state": "none", "bait_credits": None, "bait_inr": None, "outs": 0, "outs_inr": 0,
          "new_payees": 0, "escalation_steps": 0, "out_to_in_ratio": None, "rules_version": "episode-0.2"}
    r = engine.post("/v1/decide", json=req(user=user, payee=TASK_PAYEE, amount=14_000, context=episode_ctx(ep))).json()
    assert r["tier"] in ("T0", "T1") and "R10_bait_then_pay" not in r["reasons"]


# ---------- false-alarm protection ----------

def test_single_family_never_interrupts(engine, world):
    """Huge first-time payment, no phone signals, honest payee: behaviour alone is not enough."""
    user, other = users_in(world)[:2]
    payee = world[1]["users"].set_index("user_id").loc[other].upi_id
    r = engine.post("/v1/decide", json=req(user=user, payee=payee, amount=99_000)).json()
    assert r["tier"] in ("T0", "T1")


def test_registry_false_entry_alone_does_not_block(engine, world):
    rep, acc = world[1]["reports"], world[1]["accounts"]
    false = rep[rep.is_false & (rep.listed_at <= CFG.end)].identifier.iloc[0]
    assert not acc.set_index("upi_id").loc[false].is_mule
    user = users_in(world)[0]
    r = engine.post("/v1/decide", json=req(user=user, payee=false, amount=1500, entry="qr")).json()
    assert r["tier"] in ("T0", "T1")


def test_amount_cap(engine, mock, world):
    pump(mock[1], world)
    r = engine.post("/v1/decide", json=req(amount=150, context=MEENA_CONTEXT, says="government")).json()
    assert r["tier"] in ("T0", "T1")


def test_trusted_payee_suppressed_but_not_under_control(engine, world):
    user, other = users_in(world)[:2]
    payee = world[1]["users"].set_index("user_id").loc[other].upi_id
    engine.post(f"/v1/trusted/{user}/{payee}")
    calm = {"call": {"active": True, "kind": "sim", "caller_number": "+919800000001",
                     "caller_in_contacts": False, "started_min_ago": 3}, "lures": []}
    r = engine.post("/v1/decide", json=req(user=user, payee=payee, amount=60_000, context=calm)).json()
    assert r["tier"] == "T0"
    # Coached "I know this person" while someone controls the screen: the override kicks in.
    r = engine.post("/v1/decide", json=req(user=user, payee=payee, amount=60_000, context=MEENA_CONTEXT,
                                            says="government", rid="r_2")).json()
    assert r["tier"] != "T0" or "ruko_unavailable" in r["reasons"]


def _tiers_over_days(engine, user, context, n=4, payee=DEMO_MULE_UPI):
    return [engine.post("/v1/decide", json=req(user=user, payee=payee, amount=60_000, context=context, rid=f"r_{i}",
                                                ts=NOW + timedelta(days=i))).json()["tier"] for i in range(n)]


def _calm_day_tiers(families: dict, n=4):
    """The policy alone, on n calm days (stage S1: no journey under way), p_scam 0.6."""
    from api.policy import Policy
    pol = Policy()
    f = {"amount_inr": 60_000, "trusted_payee": False, "payee_registry_listed": False,
         "caller_registry_listed": False, "payee_fri_level": None, "caller_fri_level": None}
    s = {"p_scam": 0.6, "family_scores": families, "playbook": None}
    return [pol.decide(s, f, "S1", False, "u_calm", NOW + timedelta(days=i)).tier for i in range(n)]


def test_alert_budget_on_calm_days():
    """Nothing wrong with the payee (behaviour + an old lure): after 2 interruptions, only a tip."""
    assert _calm_day_tiers({"B": 0.8, "L": 0.85, "C": 0, "P": 0}) == ["T2", "T2", "T1", "T1"]


def test_alert_budget_never_applies_when_the_payee_family_is_lit():
    assert _calm_day_tiers({"B": 0.8, "L": 0, "C": 0, "P": 0.9}) == ["T2", "T2", "T2", "T2"]


def _policy_tier(families, p_scam=0.6, **feat):
    """The policy alone for one payment (stage S1, no control), with feature overrides."""
    from api.policy import Policy
    f = {"amount_inr": 60_000, "trusted_payee": False, "payee_registry_listed": False,
         "caller_registry_listed": False, "payee_fri_level": None, "caller_fri_level": None,
         "payee_approved_suspect": False, "payee_micro_anchor": False, **feat}
    s = {"p_scam": p_scam, "family_scores": families, "playbook": None}
    return Policy().decide(s, f, "S1", False, "u", NOW)


def test_approved_mule_floors_to_a_pause_even_as_the_only_family():
    """Hardened (audit §2.6): a two-analyst-approved mule pauses even with no second family lit."""
    d = _policy_tier({"B": 0, "L": 0, "C": 0, "P": 0}, p_scam=0.1, payee_approved_suspect=True)
    assert d.tier == "T3" and "approved_mule_floor" in d.applied
    # A plain single-family case with no approved mule still passes silently (corroboration gate).
    assert _policy_tier({"P": 0.9, "B": 0, "L": 0, "C": 0}, p_scam=0.8).tier == "T0"


def test_alert_budget_not_applied_during_an_anchor_pattern():
    """An anchor-then-drain keeps interrupting; it is not treated as alert fatigue (audit §2.6)."""
    from api.policy import Policy
    pol = Policy()
    f = {"amount_inr": 60_000, "trusted_payee": False, "payee_registry_listed": False,
         "caller_registry_listed": False, "payee_fri_level": None, "caller_fri_level": None,
         "payee_approved_suspect": False, "payee_micro_anchor": True}
    s = {"p_scam": 0.6, "family_scores": {"B": 0.8, "L": 0.85, "C": 0, "P": 0}, "playbook": None}
    tiers = [pol.decide(s, f, "S1", False, "u_anchor", NOW + timedelta(days=i)).tier for i in range(4)]
    assert tiers == ["T2", "T2", "T2", "T2"]


def test_alert_budget_never_silences_a_risky_payee(engine, mock, world):
    """The same calm days, but the payee is the mule-like demo account: every one is interrupted."""
    pump(mock[1], world)
    tiers = _tiers_over_days(engine, users_in(world)[0], context={"lures": []})
    assert all(t in ("T2", "T3", "T4") for t in tiers), tiers


def test_alert_budget_never_silences_an_active_journey(engine, mock, world):
    """Same payments, but an unknown caller is on the line: every one is still interrupted."""
    pump(mock[1], world)
    ctx = {"call": {"active": True, "kind": "sim", "caller_number": UNKNOWN_CALLER,
                    "caller_in_contacts": False, "started_min_ago": 5}, "lures": []}
    tiers = _tiers_over_days(engine, users_in(world)[0], context=ctx)
    assert all(t in ("T2", "T3", "T4") for t in tiers)


# ---------- unknown is not safe; RUKO never blocks because it broke ----------

def test_opted_out_user_still_gets_payee_protection(engine, mock, world):
    pump(mock[1], world)
    r = engine.post("/v1/decide", json=req(context=None, says="government")).json()
    assert r["tier"] in ("T2", "T3", "T4")       # payee + behaviour + story still corroborate
    assert "R1_live_unknown_call" not in r["reasons"]


def test_slow_intel_still_answers_in_time(engine, mock, world):
    mock[1].post("/sim/settings", json={"latency_ms": 500})
    t0 = time.perf_counter()
    r = engine.post("/v1/decide", json=req(context=MEENA_CONTEXT, says="government"))
    took = time.perf_counter() - t0
    assert r.status_code == 200 and took < 0.4
    # Phone signals alone (context + behaviour) still corroborate without any intel.
    assert r.json()["tier"] in ("T2", "T3")


def test_scorer_crash_fails_open(engine):
    def boom(_):
        raise RuntimeError("model broke")
    engine.app.state.score = boom
    r = engine.post("/v1/decide", json=req(context=MEENA_CONTEXT)).json()
    assert r == {**r, "tier": "T0", "reasons": ["ruko_unavailable"], "fail_open": True}


def test_intel_calls_run_in_parallel(engine, mock, world):
    """Six lookups at 60 ms each must take ~2 hops (resolve -> bank), not six."""
    mock[1].post("/sim/settings", json={"latency_ms": 60})
    t0 = time.perf_counter()
    engine.post("/v1/decide", json=req(context=MEENA_CONTEXT))
    assert time.perf_counter() - t0 < 0.3
    ev_ok = engine.get("/v1/evidence/verify").json()
    assert ev_ok["ok"]


# ---------- evidence ----------

def test_evidence_chain_detects_tampering(engine, mock, world):
    pump(mock[1], world)
    for i in range(3):
        engine.post("/v1/decide", json=req(context=MEENA_CONTEXT, says="government", rid=f"r_{i}",
                                           ts=NOW + timedelta(minutes=i)))
    v = engine.get("/v1/evidence/verify").json()
    assert v["ok"] and v["rows_checked"] >= 3
    db = engine.app.state.evidence.db
    db.execute("UPDATE evidence SET tier = 'T0' WHERE seq = 2")
    v = engine.get("/v1/evidence/verify").json()
    assert not v["ok"] and v["first_bad_id"]


def test_evidence_file_in_missing_folder(tmp_path):
    """A fresh clone has no logs/ folder; the store must create it, not crash the engine."""
    from evidence.store import EvidenceStore
    store = EvidenceStore(str(tmp_path / "logs" / "evidence.db"))
    store.write({"id": "e_1", "ts": "2026-11-07T10:40:00+05:30", "user_hash": "u", "payee_hash": "p",
                 "caller_hash": None, "tier": "T3", "p_scam": 0.9, "reasons": [], "playbook": None,
                 "family_scores": {}, "features": {}, "intel_status": {}, "stage_path": [],
                 "model_version": "m", "policy_version": "p"})
    assert store.verify() == {"ok": True, "rows_checked": 1, "first_bad_id": None}


# ---------- live phone demo ----------

def test_demo_clock_uses_sim_time_not_phone_time(world, mock):
    """A real phone sends today's date; with --demo-clock the engine decides at the sim clock."""
    pump(mock[1], world)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock[0]), base_url="http://mock")
    app = create_engine(world[0], intel_client=client, intel_cache_ttl_s=0, log_path=None,
                        evidence_async=False, demo_clock=True)
    sim_now = datetime.fromisoformat(mock[1].get("/sim/state").json()["now"])
    phone_ts = sim_now - timedelta(days=400)
    with TestClient(app) as engine:  # runs the lifespan, which reads the sim clock
        assert engine.get("/health").json()["demo_clock"] is True
        r = engine.post("/v1/decide", json=req(context=MEENA_CONTEXT, says="government",
                                               ts=phone_ts)).json()
        assert r["tier"] in ("T3", "T4")
        ev = engine.get(f"/v1/evidence/{r['evidence_id']}").json()
    assert abs(datetime.fromisoformat(ev["ts"]) - sim_now) < timedelta(minutes=1)


# ---------- episode events (c2-0.4) ----------

def episode_event(trigger="active", accounts=None, event_id="ev_1", user=DEMO_MEENA, state=None):
    import json as _json  # noqa: PLC0415
    body = _json.loads((Path(__file__).resolve().parents[2] / "contracts" / "examples" /
                        "episode_event_active.json").read_text(encoding="utf-8"))
    body.update(event_id=event_id, user_id=user, trigger=trigger, ts=NOW.isoformat())
    if state:
        body["summary"]["state"] = state
    if accounts is not None:
        body["accounts"] = accounts
    return body


def test_active_episode_with_mule_payee_is_high(engine, mock, world):
    pump(mock[1], world)
    r = engine.post("/v1/episode", json=episode_event()).json()
    assert r["episode_risk"] == "high" and r["case_id"]
    assert {"R10_bait_then_pay", "R3_mule_like_payee"} <= set(r["reasons"])
    assert r["message_key"] == "episode_task_scam_confirmed"
    assert any(c["case_id"] == r["case_id"] for c in engine.get("/v1/cases").json())


def test_repeated_event_id_is_ignored(engine, mock, world):
    pump(mock[1], world)
    first = engine.post("/v1/episode", json=episode_event(event_id="ev_same")).json()
    again = engine.post("/v1/episode", json=episode_event(event_id="ev_same")).json()
    assert first == again
    assert len(engine.get("/v1/cases").json()) == 1


def test_watching_episode_with_clean_accounts_is_low_or_elevated(engine, world):
    acc = [{"upi_id": "like.reward7@ybl", "role": "bait_sender", "n": 1, "inr": 150, "first_seen_min_ago": 0}]
    r = engine.post("/v1/episode", json=episode_event("watching", acc, "ev_w", state="watching")).json()
    assert r["episode_risk"] in ("low", "elevated") and r["case_id"] is None


def test_active_episode_with_clean_payees_is_only_elevated(engine, world):
    acc = [{"upi_id": "unlock.level1@ybl", "role": "payee", "n": 1, "inr": 1000, "first_seen_min_ago": 60,
            "via": "this_app", "step": 1}]
    r = engine.post("/v1/episode", json=episode_event(accounts=acc, event_id="ev_e")).json()
    assert r["episode_risk"] == "elevated" and r["case_id"] is None


def test_unreachable_intel_is_unknown(world):
    dead = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(503)), base_url="http://mock")
    app = create_engine(world[0], intel_client=dead, intel_cache_ttl_s=0, log_path=None, evidence_async=False)
    acc = [{"upi_id": "unlock.level1@ybl", "role": "payee", "n": 1, "inr": 1000, "first_seen_min_ago": 60}]
    r = TestClient(app).post("/v1/episode", json=episode_event(accounts=acc, event_id="ev_u", state="watching")).json()
    assert r["episode_risk"] == "unknown"


def test_dismissed_clears_the_users_episode_evidence(engine, mock, world):
    pump(mock[1], world)
    engine.post("/v1/episode", json=episode_event(event_id="ev_a"))
    r = engine.post("/v1/episode", json=episode_event("dismissed", [], "ev_d", state="dismissed")).json()
    assert r["episode_risk"] == "low"


# ---------- analyst console reads ----------

def test_alerts_list_the_interrupted_payments_newest_first(engine, mock, world):
    pump(mock[1], world)
    engine.post("/v1/decide", json=req(context=MEENA_CONTEXT, says="government", rid="r_alert"))
    engine.post("/v1/decide", json=req(payee=DEMO_KIRANA_UPI, amount=240, entry="qr", rid="r_quiet"))
    alerts = engine.get("/v1/alerts").json()
    assert [a["payee"] for a in alerts] == [DEMO_MULE_UPI]  # the kirana purchase was T0
    a = alerts[0]
    assert a["tier"] in ("T3", "T4") and a["reasons"] and a["evidence_id"] and a["stage_path"]
    assert "p_scam" not in a and a["user_hash"] != DEMO_MEENA
    assert engine.get("/v1/alerts?min_tier=T9").status_code == 422
    engine.post("/sim/reset")
    assert engine.get("/v1/alerts").json() == []


def test_eval_results_are_served_when_present(engine):
    r = engine.get("/v1/eval").json()
    assert set(r) == {"episode", "graph", "ai_lures"}  # null until their results files exist


def test_evidence_chain_verifies_with_scoreless_episode_records(tmp_path):
    """Episode records have no p_scam; reading them back must not break /v1/evidence/verify."""
    from evidence.store import EvidenceStore
    store = EvidenceStore(str(tmp_path / "evidence.db"))
    base = {"ts": "2026-11-07T10:40:00+05:30", "user_hash": "u", "payee_hash": None, "caller_hash": None,
            "reasons": [], "playbook": None, "family_scores": {}, "features": {}, "intel_status": {},
            "stage_path": [], "model_version": "m", "policy_version": "p"}
    store.write({**base, "id": "e_1", "tier": "T3", "p_scam": 0.91})
    store.write({**base, "id": "e_2", "tier": "episode_high", "p_scam": None})
    assert store.verify() == {"ok": True, "rows_checked": 2, "first_bad_id": None}
    assert store.get("e_2")["p_scam"] is None


# ---------- c2-0.7: saved contacts and payees paid here before ----------

def _new_payee_case(world, i=0):
    """A user, someone they never paid, and an amount 2x their usual largest (so behaviour lights)."""
    users = world[1]["users"].set_index("user_id")
    user = users_in(world)[10 + i]
    base = baseline(world, user)
    payee = next(users.loc[u].upi_id for u in users_in(world, "Delhi")[i:] if users.loc[u].upi_id not in base.known_payees)
    return user, payee, round(base.max_90d * 2)


LURE = [{"tag": "arrest_threat", "conf": 0.85, "min_ago": 600}]


def test_saved_contact_softens_new_payee_only(engine, world):
    user, payee, amount = _new_payee_case(world)
    stranger = engine.post("/v1/decide", json=req(user=user, payee=payee, amount=amount, entry="typed",
                                                  context={"lures": LURE, "payee_in_contacts": False}, rid="r_s")).json()
    contact = engine.post("/v1/decide", json=req(user=user, payee=payee, amount=amount, entry="typed",
                                                 context={"lures": LURE, "payee_in_contacts": True}, rid="r_c",
                                                 ts=NOW + timedelta(minutes=1))).json()
    assert "R6_new_payee_typed" in stranger["reasons"]
    assert "R6_new_payee_typed" not in contact["reasons"]
    # The other families are untouched: the scam-like message still counts.
    assert "R5_lure_message" in contact["reasons"] and contact["tier"] != "T0"
    ev = engine.get(f"/v1/evidence/{contact['evidence_id']}").json()
    assert ev["features"]["payee_in_contacts"] is True and ev["features"]["first_time_payee"] is True


def test_unknown_contacts_are_not_softened(engine, world):
    """Rule 1: null (contacts not readable) is treated like a stranger, never like a contact."""
    user, payee, amount = _new_payee_case(world, 1)
    r = engine.post("/v1/decide", json=req(user=user, payee=payee, amount=amount, entry="typed",
                                           context={"lures": LURE, "payee_in_contacts": None})).json()
    assert "R6_new_payee_typed" in r["reasons"]


def test_payee_paid_here_is_known_only_after_a_holding_period(engine, world):
    """Hardened (audit §2.1): a completed payment makes the payee "known" only once it is aged and
    non-trivial. A fresh payment does not, so a tiny/recent "anchor" cannot launder a mule."""
    user, payee, amount = _new_payee_case(world, 2)
    first = engine.post("/v1/decide", json=req(user=user, payee=payee, amount=amount, entry="typed",
                                               context={"lures": LURE}, rid="p_first")).json()
    assert "R6_new_payee_typed" in first["reasons"]
    engine.post("/v1/payment/outcome", json={"request_id": "p_first", "user_id": user, "payee_upi_id": payee,
                                             "amount_inr": amount, "status": "completed",
                                             "ts": (NOW + timedelta(minutes=2)).isoformat()})
    # Two hours later the payee is still NEW: a just-completed payment does not grant known status.
    soon = engine.post("/v1/decide", json=req(user=user, payee=payee, amount=amount, entry="typed",
                                              context={"lures": LURE}, rid="p_soon",
                                              ts=NOW + timedelta(hours=2))).json()
    assert "R6_new_payee_typed" in soon["reasons"]
    # After the holding period (>= 48 h) the aged payment counts, and the payee is known.
    later = engine.post("/v1/decide", json=req(user=user, payee=payee, amount=amount, entry="typed",
                                               context={"lures": LURE}, rid="p_later",
                                               ts=NOW + timedelta(hours=49))).json()
    assert "R6_new_payee_typed" not in later["reasons"]
    if later["evidence_id"]:
        assert engine.get(f"/v1/evidence/{later['evidence_id']}").json()["features"]["first_time_payee"] is False


def test_anchor_then_drain_is_flagged(engine, world):
    """A tiny sub-cap "gate pass" payment, then a drain to the same mule, is an anchor pattern that
    no longer launders the payee (known-payee poisoning, audit §2.1)."""
    user, payee, amount = _new_payee_case(world, 4)
    anchor = engine.post("/v1/decide", json=req(user=user, payee=payee, amount=150, entry="typed",
                                                context={"lures": LURE}, rid="p_anchor")).json()
    assert anchor["tier"] in ("T0", "T1")  # a sub-200 payment is capped, never interruptive
    engine.post("/v1/payment/outcome", json={"request_id": "p_anchor", "user_id": user, "payee_upi_id": payee,
                                             "amount_inr": 150, "status": "completed",
                                             "ts": (NOW + timedelta(minutes=2)).isoformat()})
    drain = engine.post("/v1/decide", json=req(user=user, payee=payee, amount=amount, entry="typed",
                                               context={"lures": LURE}, rid="p_drain",
                                               ts=NOW + timedelta(minutes=30))).json()
    # The drain still sees a new payee (not laundered) and the anchor pattern.
    assert "R6_new_payee_typed" in drain["reasons"]
    if drain["evidence_id"]:
        feats = engine.get(f"/v1/evidence/{drain['evidence_id']}").json()["features"]
        assert feats["first_time_payee"] is True and feats["payee_micro_anchor"] is True
