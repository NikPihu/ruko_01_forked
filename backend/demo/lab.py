"""Scam lab: a judge plays the scammer against the emulator, end to end.

The judge, on the console's "AI scammer" page, sends an SMS or rings the victim's phone, or runs a
ready-made scam workflow. The victim (a presenter) is on the emulator using Cache Pay and pays as a
real person would. The page then shows, from the scammer's side, whether the scam worked.

The lab only plays the *network*: it delivers what the judge typed, or a preset from the repo's
synthetic test messages (`backend/evalsuite/ai_lures.jsonl`), through `adb emu`, so the message
really lands in the emulator's Messages app and the call really rings. RUKO's engine still sees
only what the phone sends (rule 2); the lab never writes message text anywhere but its own memory,
and it never takes part in a decision (rule 13). It exists only when the server runs with `--lab`,
and `adb emu` only works on emulators, never on a real phone.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

IST = timezone(timedelta(hours=5, minutes=30))
ROOT = Path(__file__).resolve().parents[2]
LURES = ROOT / "backend" / "evalsuite" / "ai_lures.jsonl"

NUMBER = re.compile(r"^\+?\d{3,15}$")
MAX_TEXT = 480
CALL_ACTIONS = {"ring": "call", "answer": "accept", "hangup": "cancel"}
UNKNOWN_NUMBERS = ["9812345670", "9800011122", "7012345678"]
DEMO_MULE = "secure.settlement.desk@okaxis"
KIRANA = "shreeganesh.kirana@okaxis"
CAMPAIGN_UPI = "kyc.refund.desk@ybl"     # a fresh mule no bank or registry knows

Runner = Callable[[list[str]], "tuple[int, str]"]


class LabError(ValueError):
    """Bad input or no emulator: shown to the judge in words."""


class SmsIn(BaseModel):
    sender: str = Field(alias="from", min_length=3, max_length=16)
    text: str = Field(min_length=1, max_length=MAX_TEXT)


class CallIn(BaseModel):
    number: str = Field(min_length=3, max_length=16)
    action: str = Field(pattern="^(ring|answer|hangup)$")


def find_adb() -> Optional[str]:
    """Like scripts/dev.ps1: the Android SDK's adb, else adb on PATH."""
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk" / "platform-tools" / "adb.exe"
    if local.exists():
        return str(local)
    home = Path(os.environ.get("ANDROID_HOME", "")) / "platform-tools" / "adb"
    return str(home) if home.exists() else shutil.which("adb")


def _subprocess_runner(cmd: list[str]) -> tuple[int, str]:
    """Runs an argument list (never a shell string), so nothing the judge types is interpreted."""
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=15)
    return r.returncode, (r.stdout + r.stderr).strip()


def clean_number(raw: str) -> str:
    s = re.sub(r"[\s-]", "", raw or "")
    if not NUMBER.match(s):
        raise LabError("a phone number is 3 to 15 digits (a leading + is fine)")
    return s.lstrip("+")   # the emulator takes digits only


def clean_text(raw: str) -> str:
    s = " ".join((raw or "").split())   # one line: the emulator console reads line by line
    if not s or len(s) > MAX_TEXT:
        raise LabError(f"a message is 1 to {MAX_TEXT} characters")
    return s


class Adb:
    def __init__(self, runner: Optional[Runner] = None, adb: Optional[str] = None) -> None:
        self.run = runner or _subprocess_runner
        self.adb = adb if adb is not None else find_adb()

    def emulator(self) -> Optional[str]:
        """The first running emulator (`emulator-5554`), or None."""
        if not self.adb:
            return None
        code, out = self.run([self.adb, "devices"])
        if code != 0:
            return None
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].startswith("emulator-") and parts[1] == "device":
                return parts[0]
        return None

    def _emu(self, *args: str) -> str:
        serial = self.emulator()
        if serial is None:
            raise LabError("no emulator is running: start one in Android Studio, then try again")
        code, out = self.run([self.adb, "-s", serial, "emu", *args])
        if code != 0 or out.upper().startswith("KO"):
            raise LabError(f"the emulator refused it: {out or code}")
        return serial

    def sms(self, sender: str, text: str) -> str:
        return self._emu("sms", "send", clean_number(sender), clean_text(text))

    def call(self, number: str, action: str) -> str:
        if action not in CALL_ACTIONS:
            raise LabError("a call action is ring, answer or hangup")
        return self._emu("gsm", CALL_ACTIONS[action], clean_number(number))


# ---------- presets and workflows (data; the server does the set-up) ----------

def _lures() -> list[dict]:
    return [json.loads(line) for line in LURES.read_text(encoding="utf-8").splitlines() if line.strip()]


def _first(tag: str, lang: str = "en") -> str:
    return next(r["text"] for r in _lures() if r["tag"] == tag and r["lang"] == lang)


def presets(contacts: list[dict]) -> dict:
    """Messages from the synthetic test set (AI-written scams and everyday messages) and numbers."""
    rows = _lures()
    return {
        "scam": [{"tag": r["tag"], "lang": r["lang"], "text": r["text"]} for r in rows if r["tag"] != "normal"],
        "everyday": [{"lang": r["lang"], "text": r["text"]} for r in rows if r["tag"] == "normal"],
        "numbers": {"unknown": UNKNOWN_NUMBERS,
                    "contacts": [{"name": c["name"], "mobile": c["mobile"]} for c in contacts[:4]]},
    }


@dataclass
class Workflow:
    id: str
    title: str
    flagged: bool
    story: str                       # one line, what the scammer is doing
    expect: str                      # in words
    expect_tiers: list[str]          # tiers that count as the expected result
    sms: Optional[dict] = None       # {"from", "text"}
    call: Optional[str] = None       # number that rings
    victim_steps: list[str] = field(default_factory=list)
    payee: str = ""
    amount: int = 0
    prepare: str = ""                # what the server sets up first, in words ("" = nothing)


def workflows(contacts: list[dict], fresh_mule: str) -> list[Workflow]:
    friend = next((c for c in contacts if c.get("sent_to_user")), contacts[0] if contacts else None)
    friend_mobile = friend["mobile"] if friend else "9876543210"
    friend_name = friend["name"] if friend else "a saved contact"
    unknown = UNKNOWN_NUMBERS[0]
    return [
        Workflow(
            id="flagged", title="Flagged: scam call + message", flagged=True,
            story="A fake 'officer' texts an arrest threat, then calls and keeps the victim on the line.",
            expect="RUKO interrupts: a warning or a pause (T2+; T3 under the rules scorer), reasons in words",
            expect_tiers=["T2", "T3", "T4"],
            sms={"from": unknown, "text": _first("arrest_threat")}, call=unknown,
            victim_steps=["Answer the incoming call and keep it on.",
                          f"In Cache Pay, pay Rs 95,000 to {DEMO_MULE} (typed); if asked, say 'Government'.",
                          "Read RUKO's alert, then Cancel (or pay anyway)."],
            payee=DEMO_MULE, amount=95_000,
            prepare="Makes the demo mule look like a mule at its bank (many strangers, money forwarded fast).",
        ),
        Workflow(
            id="everyday", title="Not flagged: everyday payment", flagged=False,
            story=f"{friend_name} (a saved contact) sends an ordinary message. No call, no pressure.",
            expect="No interruption: straight to the PIN (T0/T1)", expect_tiers=["T0", "T1"],
            sms={"from": friend_mobile, "text": next(r["text"] for r in _lures() if r["tag"] == "normal"
                                                       and r["text"].startswith("Mom"))},
            victim_steps=[f"In Cache Pay, pay Rs 150 to {KIRANA} (the local shop).", "Enter the PIN."],
            payee=KIRANA, amount=150,
        ),
        Workflow(
            id="campaign", title="Same scam, many phones", flagged=True,
            story="An AI crew sends reworded KYC messages to many people, all with the same new UPI ID.",
            expect="RUKO warns: 'this account is being sent to many people in scam messages' (R13, T2+)",
            expect_tiers=["T2", "T3", "T4"],
            sms={"from": UNKNOWN_NUMBERS[1], "text": f"{_first('kyc')} UPI ID: {CAMPAIGN_UPI}"},
            victim_steps=[f"In Cache Pay, pay Rs 4,000 to {CAMPAIGN_UPI} (typed).",
                          "Read RUKO's alert; the console's Overview shows it under 'Spreading now'."],
            payee=CAMPAIGN_UPI, amount=4_000,
            prepare="Three other phones report the same UPI ID in their scam messages (early warnings).",
        ),
        Workflow(
            id="new_scam", title="New scam, behaviour only", flagged=True,
            story="A scam RUKO has no playbook for: a 'hospital desk' asks for money for a relative, "
                  "and many people pay the same fresh account.",
            expect="RUKO still steps in on behaviour (no scam name), and the case appears under "
                   "Emerging patterns", expect_tiers=["T1", "T2", "T3", "T4"],
            sms={"from": UNKNOWN_NUMBERS[2],
                 "text": f"[RUKO lab test] Hospital desk: payment needed for a patient. UPI ID: {fresh_mule}"},
            call=UNKNOWN_NUMBERS[2],
            victim_steps=["Answer the incoming call and keep it on.",
                          "In Messages, copy the UPI ID; switch to Cache Pay and paste it.",
                          "Pay Rs 25,000 and read RUKO's alert."],
            payee=fresh_mule, amount=25_000,
            prepare="Nine other people pay the same fresh account the same amount, in a burst.",
        ),
    ]


def as_dict(w: Workflow) -> dict:
    return asdict(w)


# ---------- what the scammer sees ----------

def verdict(tier: str, status: Optional[str]) -> dict:
    """The outcome from the scammer's side, in words."""
    interrupted = tier in ("T2", "T3", "T4")
    if interrupted and status == "cancelled":
        return {"result": "stopped", "words": "Stopped by RUKO: the victim cancelled after the warning."}
    if interrupted and status == "completed":
        return {"result": "paid_anyway", "words": "Money received: the victim paid anyway, despite RUKO's warning."}
    if interrupted:
        return {"result": "interrupted", "words": "RUKO stepped in: the victim is looking at the warning."}
    if status == "completed":
        return {"result": "paid", "words": "Money received: RUKO saw nothing wrong."}
    if status == "cancelled":
        return {"result": "cancelled", "words": "The victim cancelled on their own."}
    return {"result": "not_flagged", "words": "Not flagged: the victim went straight to the PIN."}


class LabState:
    """What the lab sent (for the page), and which users it simulated (not the victim)."""

    def __init__(self) -> None:
        self.sent: deque[dict] = deque(maxlen=50)
        self.simulated: set[str] = set()

    def reset(self) -> None:
        self.sent.clear()
        self.simulated.clear()

    def log(self, kind: str, **detail) -> None:
        self.sent.appendleft({"ts": datetime.now(IST).isoformat(), "kind": kind, **detail})


# ---------- the endpoints (registered only with --lab) ----------

VICTIM = "u_demo_meena"


def routes(app, *, data_dir: Path, intel_url: str, store, explain_fn, reset_fn,
           adb: Optional[Adb] = None) -> None:
    """Adds /v1/lab/*. `explain_fn(payment, details)` is the analyst explanation; `reset_fn` is
    /sim/reset. `app.state.lab_client(base)` (tests swap it) gives the HTTP client the workflows use
    to act as other phones, through the public API like the demo agents."""
    import httpx

    from api.explain import REASON_TEXT
    from evidence.store import pseudonym

    state, device = LabState(), adb or Adb()
    app.state.lab = state
    app.state.lab_adb = device
    def own_client(base: str):
        return httpx.Client(base_url=base, timeout=30)
    app.state.lab_client = own_client
    app.state.lab_intel = lambda: httpx.Client(base_url=intel_url, timeout=30)
    cache: dict = {}

    def contacts() -> list[dict]:
        if "contacts" not in cache:
            try:
                from sim.contacts import address_book
                cache["contacts"] = address_book(Path(data_dir))
            except Exception:   # no generated data: the lab still sends what the judge types
                cache["contacts"] = []
        return cache["contacts"]

    def world():
        if "world" not in cache:
            try:
                from demo import agents
                cache["world"] = agents.load_world(Path(data_dir))
            except Exception:
                cache["world"] = None
        return cache["world"]

    def flows() -> dict[str, Workflow]:
        w = world()
        return {f.id: f for f in workflows(contacts(), w.fresh_mule if w else "fresh.mule.demo@okaxis")}

    def wrap(fn, *args):
        try:
            return fn(*args)
        except LabError as e:
            raise HTTPException(409 if "emulator" in str(e) else 422, str(e))
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "the emulator did not answer in time")

    @app.get("/v1/lab/status")
    def lab_status() -> dict:
        return {"lab": True, "adb": device.adb, "emulator": device.emulator(), "victim": VICTIM}

    @app.get("/v1/lab/presets")
    def lab_presets() -> dict:
        return presets(contacts())

    @app.post("/v1/lab/sms")
    def lab_sms(body: SmsIn) -> dict:
        serial = wrap(device.sms, body.sender, body.text)
        state.log("sms", **{"from": clean_number(body.sender), "chars": len(clean_text(body.text))})
        return {"sent": True, "emulator": serial}

    @app.post("/v1/lab/call")
    def lab_call(body: CallIn) -> dict:
        serial = wrap(device.call, body.number, body.action)
        state.log("call", number=clean_number(body.number), action=body.action)
        return {"done": True, "emulator": serial}

    @app.get("/v1/lab/sent")
    def lab_sent() -> dict:
        return {"sent": list(state.sent)}

    @app.get("/v1/lab/workflows")
    def lab_workflows() -> dict:
        return {"victim": VICTIM, "workflows": [as_dict(f) for f in flows().values()],
                "app_switches": ["SMS scam check", "Call signals", "Session checks", "Early warnings (optional)"]}

    @app.post("/v1/lab/workflows/{flow_id}/prepare")
    def lab_prepare(flow_id: str, request: Request) -> dict:
        """The server-side set-up: other (simulated) phones and banks, never the victim's phone."""
        f = flows().get(flow_id)
        if f is None:
            raise HTTPException(404, "no such workflow")
        w = world()
        if f.prepare and w is None:
            raise HTTPException(409, "generated data is missing (run scripts/dev.ps1 once)")
        from demo import agents
        own = app.state.lab_client is own_client
        c, mock = app.state.lab_client(str(request.base_url).rstrip("/")), app.state.lab_intel()
        done: dict = {"workflow": f.id, "prepared": f.prepare or "nothing to set up"}
        try:
            try:
                now = datetime.fromisoformat(mock.get("/sim/state").json()["now"])
            except Exception:
                now = datetime.now(IST)
            if f.id == "flagged":
                agents.pump_mule(mock, w)
            elif f.id == "campaign":
                for i, u in enumerate(w.users[40:43]):
                    state.simulated.add(u)
                    c.post("/v1/watch", json={"event_id": f"lab-{u}-{now.timestamp():.0f}", "user_id": u,
                                              "kind": "lure_seen", "ts": (now - timedelta(minutes=10 - 3 * i)).isoformat(),
                                              "lure_tag": "kyc", "lure_conf": 0.85, "source": "sms",
                                              "handles": [{"kind": "upi", "value": CAMPAIGN_UPI}]})
                done["phones"] = 3
            elif f.id == "new_scam":
                paid = agents.relative_emergency(c, w, now, w.users[20], victims=9)
                state.simulated.update(w.users[20:29])
                done["tiers"] = [r.get("tier") for r in paid]
        finally:
            if own:
                c.close()
                mock.close()
        state.log("prepare", workflow=f.id)
        return done

    @app.post("/v1/lab/workflows/{flow_id}/send")
    def lab_send(flow_id: str) -> dict:
        """The scammer's move: the workflow's message, then its call (if any), to the emulator."""
        f = flows().get(flow_id)
        if f is None:
            raise HTTPException(404, "no such workflow")
        out: dict = {"workflow": f.id}
        if f.sms:
            out["emulator"] = wrap(device.sms, f.sms["from"], f.sms["text"])
            state.log("sms", **{"from": f.sms["from"], "chars": len(f.sms["text"]), "workflow": f.id})
        if f.call:
            out["emulator"] = wrap(device.call, f.call, "ring")
            state.log("call", number=f.call, action="ring", workflow=f.id)
        return out

    @app.get("/v1/lab/latest")
    def lab_latest(user_id: str = VICTIM, workflow: Optional[str] = None) -> dict:
        """The victim's newest payment, from the scammer's side: did it work? Analyst words, no
        message text (the engine never had any)."""
        rows = store.transactions(user_hash=pseudonym(user_id), limit=1)
        if not rows:
            return {"payment": None}
        p = rows[0]
        ex = explain_fn(p, store.details(p["payment_id"]))
        out = {"payment": {k: p[k] for k in ("payment_id", "payee_upi", "amount_inr", "ts", "tier", "playbook",
                                             "status", "message_key")},
               "reasons": [{"code": r, "text": REASON_TEXT.get(r, r)} for r in p["reasons"]],
               "headline": ex["summary"]["headline"], "lit": ex["scores"]["lit_families"],
               **verdict(p["tier"], p["status"])}
        f = flows().get(workflow) if workflow else None
        if f is not None:
            out["expected"] = {"workflow": f.id, "words": f.expect, "met": p["tier"] in f.expect_tiers,
                               "same_payee": p["payee_upi"] == f.payee}
        return out

    @app.post("/v1/lab/reset")
    async def lab_reset() -> dict:
        await reset_fn()
        state.reset()
        return {"ok": True}
