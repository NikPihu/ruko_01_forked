"""The scam lab (demo/lab.py): a judge plays the scammer against the emulator. adb is faked here."""
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

import api.main
from api.main import create_app as create_engine
from demo import lab
from test_decide import NOW, mock, world  # noqa: F401

SECRET = "LAB-TEXT-MUST-NOT-BE-STORED-7f3a"


class FakeAdb:
    """Records every command; `devices` lists one emulator unless told otherwise."""

    def __init__(self, emulator: bool = True):
        self.calls: list[list[str]] = []
        self.emulator = emulator

    def __call__(self, cmd: list[str]) -> tuple[int, str]:
        self.calls.append(cmd)
        if cmd[1:] == ["devices"]:
            return 0, "List of devices attached\nemulator-5554\tdevice\n" if self.emulator else "List of devices attached\n"
        return 0, "OK"


def make(world, mock, lab_on=True, emulator=True):
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock[0]), base_url="http://mock")
    app = create_engine(world[0], intel_client=client, intel_cache_ttl_s=0, log_path=None,
                        evidence_async=False, intel_budget_s=5.0, lab=lab_on)
    tc = TestClient(app)
    fake = FakeAdb(emulator)
    if lab_on:
        app.state.lab_adb.run, app.state.lab_adb.adb = fake, "adb"
        app.state.lab_client = lambda base: tc
        app.state.lab_intel = lambda: mock[1]
    return tc, fake


@pytest.fixture()
def engine(world, mock, monkeypatch):
    monkeypatch.setattr(api.main, "DEADLINE_S", 10.0)
    return make(world, mock)


def test_lab_is_off_without_the_flag(world, mock):
    tc, _ = make(world, mock, lab_on=False)
    assert tc.get("/v1/lab/status").status_code == 404
    assert tc.post("/v1/lab/sms", json={"from": "9812345670", "text": "hi"}).status_code == 404


def test_sms_and_call_are_argument_lists_to_the_emulator(engine):
    tc, fake = engine
    assert tc.get("/v1/lab/status").json()["emulator"] == "emulator-5554"
    r = tc.post("/v1/lab/sms", json={"from": "+91 98123-45670", "text": "line one\nline two; rm -rf /"})
    assert r.status_code == 200
    assert fake.calls[-1] == ["adb", "-s", "emulator-5554", "emu", "sms", "send", "919812345670",
                              "line one line two; rm -rf /"]
    for action, word in (("ring", "call"), ("answer", "accept"), ("hangup", "cancel")):
        assert tc.post("/v1/lab/call", json={"number": "9812345670", "action": action}).status_code == 200
        assert fake.calls[-1] == ["adb", "-s", "emulator-5554", "emu", "gsm", word, "9812345670"]


@pytest.mark.parametrize("body", [{"from": "abc", "text": "hi"}, {"from": "12", "text": "hi"},
                                  {"from": "9812345670", "text": ""}, {"from": "9812345670", "text": "x" * 481},
                                  {"from": "98123;45670", "text": "hi"}])
def test_bad_sms_is_refused(engine, body):
    tc, fake = engine
    assert tc.post("/v1/lab/sms", json=body).status_code == 422
    assert not any("sms" in c for c in fake.calls)


def test_bad_call_action_is_refused(engine):
    tc, _ = engine
    assert tc.post("/v1/lab/call", json={"number": "9812345670", "action": "dial"}).status_code == 422


def test_no_emulator_is_a_clear_error(world, mock):
    tc, _ = make(world, mock, emulator=False)
    r = tc.post("/v1/lab/sms", json={"from": "9812345670", "text": "hi"})
    assert r.status_code == 409 and "emulator" in r.json()["detail"]


def test_presets_come_from_the_synthetic_set(engine):
    tc, _ = engine
    p = tc.get("/v1/lab/presets").json()
    assert len(p["scam"]) == 26 and len(p["everyday"]) == 14
    assert p["numbers"]["unknown"] and p["numbers"]["contacts"]


def test_four_workflows_both_outcomes(engine):
    tc, _ = engine
    flows = {f["id"]: f for f in tc.get("/v1/lab/workflows").json()["workflows"]}
    assert set(flows) == {"flagged", "everyday", "campaign", "new_scam", "otp_call"}
    assert not flows["everyday"]["flagged"] and all(flows[k]["flagged"] for k in ("flagged", "campaign", "new_scam"))


def decide(tc, payee, amount, context=None, entry="typed"):
    rid = str(uuid.uuid4())
    r = tc.post("/v1/decide", json={"request_id": rid, "user_id": lab.VICTIM, "payee_upi_id": payee,
                                    "amount_inr": amount, "entry_method": entry, "ts": NOW.isoformat(),
                                    "context": context}).json()
    return rid, r


def test_campaign_prepare_seeds_three_phones(engine):
    tc, _ = engine
    assert tc.post("/v1/lab/workflows/campaign/prepare").json()["phones"] == 3
    handles = tc.get("/v1/campaigns/spreading").json()["handles"]
    assert any(h["value"] == lab.CAMPAIGN_UPI and h["users"] >= 3 for h in handles)


def test_new_scam_prepare_pays_the_fresh_mule(engine):
    tc, _ = engine
    tiers = tc.post("/v1/lab/workflows/new_scam/prepare").json()["tiers"]
    assert len(tiers) == 9 and all(t != "T0" for t in tiers)


def test_send_delivers_message_then_call(engine):
    tc, fake = engine
    tc.post("/v1/lab/workflows/flagged/send")
    kinds = [c[4:6] for c in fake.calls if "emu" in c]
    assert kinds == [["sms", "send"], ["gsm", "call"]]


def test_latest_is_the_victims_newest_payment_in_words(engine):
    tc, _ = engine
    assert tc.get("/v1/lab/latest").json()["payment"] is None
    tc.post("/v1/lab/workflows/new_scam/prepare")          # other users' payments are not the victim's
    assert tc.get("/v1/lab/latest").json()["payment"] is None
    rid, r = decide(tc, lab.KIRANA, 150, entry="qr")
    out = tc.get("/v1/lab/latest", params={"workflow": "everyday"}).json()
    assert out["payment"]["payment_id"] == rid and out["payment"]["tier"] == r["tier"]
    assert out["result"] == "not_flagged" and out["headline"]
    assert out["expected"]["same_payee"] is True
    tc.post("/v1/payment/outcome", json={"request_id": rid, "user_id": lab.VICTIM, "payee_upi_id": lab.KIRANA,
                                         "amount_inr": 150, "status": "completed", "ts": NOW.isoformat()})
    assert tc.get("/v1/lab/latest").json()["result"] in ("paid", "paid_anyway")


def test_message_text_is_never_stored(engine):
    tc, _ = engine
    tc.post("/v1/lab/sms", json={"from": "9812345670", "text": SECRET})
    decide(tc, lab.KIRANA, 150)
    assert SECRET not in str(tc.get("/v1/lab/sent").json())
    assert SECRET not in str(tc.get("/v1/transactions").json())
    assert SECRET not in str(tc.get("/v1/evidence/verify").json())


def test_reset_clears_the_lab(engine):
    tc, _ = engine
    tc.post("/v1/lab/sms", json={"from": "9812345670", "text": "hi"})
    decide(tc, lab.KIRANA, 150)
    assert tc.post("/v1/lab/reset").json() == {"ok": True}
    assert tc.get("/v1/lab/sent").json() == {"sent": []}
    assert tc.get("/v1/lab/latest").json()["payment"] is None


@pytest.mark.parametrize("tier,status,result", [("T3", "cancelled", "stopped"), ("T3", "completed", "paid_anyway"),
                                                ("T2", "checked", "interrupted"), ("T0", "completed", "paid"),
                                                ("T1", "checked", "not_flagged")])
def test_verdict_words(tier, status, result):
    assert lab.verdict(tier, status)["result"] == result


def test_the_lab_follows_whichever_demo_account_paid_last(engine, world):
    tc, _ = engine
    people = {v["user_id"] for v in tc.get("/v1/lab/status").json()["victims"]}
    assert {"u_demo_meena", "u_001435"} <= people             # Meena and Rahul (app's demo accounts)
    w = __import__("demo.agents", fromlist=["load_world"]).load_world(world[0])
    assert not people & set(w.users[:60])                       # the lab and demo agents never act as them
    rid = str(uuid.uuid4())
    tc.post("/v1/decide", json={"request_id": rid, "user_id": "u_001435", "payee_upi_id": lab.KIRANA,
                                "amount_inr": 150, "entry_method": "qr", "ts": NOW.isoformat(), "context": None})
    assert tc.get("/v1/lab/status").json()["victim"] == "u_001435"
    out = tc.get("/v1/lab/latest").json()
    assert out["victim"] == "u_001435" and out["payment"]["payment_id"] == rid
    assert tc.get("/v1/lab/latest", params={"user_id": "u_demo_meena"}).json()["payment"] is None


def test_otp_rings_first_and_the_code_comes_once_the_call_is_on(engine):
    tc, fake = engine
    f = next(x for x in tc.get("/v1/lab/workflows").json()["workflows"] if x["id"] == "otp_call")
    assert f["sms_after_call"] and f["on_phone_only"] and "OTP" in f["sms"]["text"]
    tc.post("/v1/lab/workflows/otp_call/send", params={"part": "call"})
    assert [c[4:6] for c in fake.calls if "emu" in c] == [["gsm", "call"]]
    tc.post("/v1/lab/workflows/otp_call/send", params={"part": "sms"})
    assert [c[4:6] for c in fake.calls if "emu" in c][-1] == ["sms", "send"]
    assert tc.post("/v1/lab/workflows/otp_call/send", params={"part": "fax"}).status_code == 422
