from datetime import timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from intel_mock.app import create_app
from sim.accounts import DEMO_KIRANA_UPI, DEMO_MULE_UPI
from sim.config import SimConfig
from sim.generate import build_world, write_world

CFG = SimConfig(seed=1, n_users=400, n_days=20, scam_rate=0.05)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    out = tmp_path_factory.mktemp("data")
    tables = build_world(CFG)
    write_world(tables, CFG, out)
    return out, tables


@pytest.fixture()
def c(world):
    client = TestClient(create_app(world[0]))
    yield client
    client.post("/sim/reset")


def _risk(c, upi):
    bank = c.get(f"/npci/resolve/{upi}").json()["bank_code"]
    return c.get(f"/banks/{bank}/payee-risk/{upi}")


def _acc(world):
    return world[1]["accounts"]


# ---------- NPCI ----------

def test_resolve_returns_only_public_fields(c):
    r = c.get(f"/npci/resolve/{DEMO_MULE_UPI}")
    assert r.status_code == 200
    body = r.json()
    assert body["registered_name"] and body["bank"] == "Axis Bank"
    for secret in ("is_mule", "mule_kind", "created_at", "kyc_at", "mobile", "account_id"):
        assert secret not in body


def test_resolve_rejects_unknown(c):
    assert c.get("/npci/resolve/someone@nosuchbank").json()["detail"]["reason"] == "unknown_handle"
    assert c.get("/npci/resolve/nobody.here@okaxis").json()["detail"]["reason"] == "no_such_vpa"
    assert c.get("/npci/resolve/no-at-sign").status_code == 400


def test_number_mapper(c, world):
    acct = _acc(world).iloc[0]
    assert c.get(f"/npci/mapper/{acct.mobile}").json()["upi_id"] == acct.upi_id


# ---------- banks ----------

def test_bank_answers_only_for_its_own_accounts(c):
    assert c.get(f"/banks/state-bank-of-india/payee-risk/{DEMO_MULE_UPI}").status_code == 404


def test_visibility_modes(c, world):
    acc = _acc(world)
    outsider = acc[~acc.partner_bank & ~acc.is_mule].iloc[0].upi_id
    assert _risk(c, outsider).status_code == 403          # default: partners only
    c.post("/sim/settings", json={"visibility": "dpip"})
    assert _risk(c, outsider).status_code == 200
    c.post("/sim/settings", json={"visibility": "none"})
    assert _risk(c, DEMO_MULE_UPI).status_code == 403


def test_kirana_and_mule_look_different(c, world):
    c.post("/sim/settings", json={"visibility": "dpip"})
    k = _risk(c, DEMO_KIRANA_UPI).json()
    assert k["features"]["repeat_payer_ratio_30d"] > 0.7
    assert k["features"]["pass_through_7d"] in (None, 0)
    assert k["mulehunter"]["score"] < 0.3
    acc = _acc(world)
    old_mules = acc[acc.is_mule & acc.mule_kind.isin(["plain", "merchant_disguised"])
                    & (acc.created_at < CFG.end - timedelta(days=12))]
    scores = [_risk(c, u).json()["mulehunter"]["score"] for u in old_mules.upi_id]
    scored = [s for s in scores if s is not None]
    assert scored and max(scored) > 0.7


def test_fresh_mule_not_scored_but_features_visible(c):
    r = _risk(c, DEMO_MULE_UPI).json()
    assert r["mulehunter"]["score"] is None             # too new for the daily batch model
    assert r["features"]["uniq_payers_7d"] >= 10         # but the live features already show fan-in
    assert r["features"]["pass_through_7d"] > 0.6


def test_no_peeking_into_the_future(c):
    now_7d = _risk(c, DEMO_MULE_UPI).json()["features"]["uniq_payers_7d"]
    c.post("/sim/clock", json={"advance_hours": -48})
    earlier = _risk(c, DEMO_MULE_UPI).json()["features"]["uniq_payers_7d"]
    assert earlier < now_7d
    c.post("/sim/clock", json={"advance_hours": -72})    # before the mule was opened
    assert c.get(f"/npci/resolve/{DEMO_MULE_UPI}").status_code == 404


def test_live_payments_change_features(c, world):
    payers = _acc(world).query("holder_type == 'person' and not is_mule").upi_id[:12]
    before = _risk(c, DEMO_MULE_UPI).json()["features"]["uniq_payers_6h"]
    for p in payers:
        assert c.post("/npci/pay", json={"from_upi": p, "to_upi": DEMO_MULE_UPI, "amount": 900}).status_code == 200
    after = _risk(c, DEMO_MULE_UPI).json()["features"]["uniq_payers_6h"]
    assert after >= before + len(payers)
    assert c.post("/npci/pay", json={"from_upi": payers.iloc[0], "to_upi": DEMO_MULE_UPI,
                                     "amount": 150_000}).status_code == 400


# ---------- I4C registry ----------

def test_registry_lists_only_after_processing(c, world):
    rep = world[1]["reports"]
    r = rep[(rep.identifier_type == "upi_id") & ~rep.is_false].sort_values("listed_at").iloc[0]
    c.post("/sim/clock", json={"set": (r.listed_at - timedelta(minutes=1)).isoformat()})
    others_before = rep[(rep.identifier == r.identifier) & (rep.listed_at < r.listed_at)]
    assert c.get("/i4c/registry", params={"upi_id": r.identifier}).json()["listed"] == (len(others_before) > 0)
    c.post("/sim/clock", json={"set": (r.listed_at + timedelta(minutes=1)).isoformat()})
    assert c.get("/i4c/registry", params={"upi_id": r.identifier}).json()["listed"] is True


def test_registry_has_false_entries_and_misses_fresh_mule(c, world):
    rep = world[1]["reports"]
    false = rep[rep.is_false & (rep.listed_at <= CFG.end)]
    assert c.get("/i4c/registry", params={"upi_id": false.iloc[0].identifier}).json()["listed"]
    assert not c.get("/i4c/registry", params={"upi_id": DEMO_MULE_UPI}).json()["listed"]
    assert c.get("/i4c/registry").status_code == 400


# ---------- DoT FRI ----------

def test_fri_levels(c, world):
    rep = world[1]["reports"]
    mobiles = rep[(rep.identifier_type == "mobile") & rep.identifier.str.startswith("+91")
                  & (rep.listed_at <= CFG.end - timedelta(days=1))]
    top = mobiles.identifier.value_counts().index[0]
    assert c.get(f"/dot/fri/{top}").json()["risk"] in ("MEDIUM", "HIGH", "VERY_HIGH")
    honest = _acc(world).iloc[0].mobile
    assert c.get(f"/dot/fri/{honest}").json()["risk"] == "NONE"
    assert c.get("/dot/fri/+923001234567").json()["reason"] == "not_an_indian_number"


# ---------- sim controls ----------

def test_latency_knob(c):
    import time
    t0 = time.perf_counter()
    c.get(f"/npci/resolve/{DEMO_MULE_UPI}", params={"delay_ms": 300})
    assert time.perf_counter() - t0 >= 0.3


def test_reset_restores_everything(c, world):
    payer = _acc(world).query("holder_type == 'person' and not is_mule").upi_id.iloc[0]
    c.post("/npci/pay", json={"from_upi": payer, "to_upi": DEMO_MULE_UPI, "amount": 900})
    c.post("/sim/settings", json={"visibility": "none", "latency_ms": 10})
    c.post("/sim/clock", json={"advance_hours": 5})
    s = c.post("/sim/reset").json()
    assert s["live_payments"] == 0 and s["visibility"] == "partner" and s["latency_ms"] == 0
    assert pd.Timestamp(s["now"]) == pd.Timestamp(CFG.end)
