# Scam lab: a judge plays the AI scammer, end to end

**What it does.** Two people, two screens:
- **The judge is the scammer**, on the console's **AI scammer** page
  (`http://127.0.0.1:<api port>/console/#/lab`). They send SMS (typed, or picked from the
  synthetic test set), ring the phone, or run a ready-made scam, then tell the victim who to pay.
- **The victim** (a presenter) is on the **emulator, using Cache Pay**. The message really lands in
  Messages and the call really rings. They pay as a real person would, and RUKO's alert appears in
  the app as usual.

The page then shows, from the scammer's side, **"Did your scam work?"**:
- *Money received* (paid, no alert, or paid anyway);
- *Stopped by RUKO* (alert, then cancelled);
- *RUKO stepped in* (the alert is on screen);
- *Not flagged*.

Next to it: RUKO's tier, the reasons in words, whether it matched the workflow, and a link to the
analyst "Why".

**Run it** (on the laptop with Android Studio):
1. Start the emulator.
2. Run `scripts\dev.ps1`; it passes `--lab` to the API.
3. In Cache Pay, switch on SMS scam check, Call signals and Session checks (Early warnings is
   optional).
4. Open the console → **AI scammer**. The status strip must say "Emulator emulator-5554".

**Ready-made scams** (`backend/demo/lab.py` `workflows()`):

| Workflow | Set up (server, other simulated phones) | Scammer sends | Victim does in Cache Pay | Expected |
|---|---|---|---|---|
| Flagged: scam call + message | the demo mule looks like a mule at its bank | arrest-threat SMS + a call from an unknown number | answer, keep the call on, pay ₹95,000 to `secure.settlement.desk@okaxis` | T2+ (T2 on `lgbm-0.2`, T3 on the rules) |
| Not flagged: everyday payment | — | an everyday SMS from a saved contact | pay ₹150 to `shreeganesh.kirana@okaxis` | T0/T1, straight to the PIN |
| Same scam, many phones | 3 other phones report the same UPI ID in scam messages (`/v1/watch`) | a KYC SMS carrying `kyc.refund.desk@ybl` | pay that UPI ₹4,000 | T2+ with R13 first; Overview "Spreading now" lists it |
| New scam, behaviour only | 9 other people pay a fresh mule ₹25,000 in a burst | an SMS with that UPI + a call | answer, copy the UPI from Messages, paste it in Cache Pay, pay ₹25,000 | interrupted with no scam name; **Emerging patterns** shows it |

Checked here against the live `lgbm-0.2` server, with the phone's requests replayed: flagged T2,
everyday T0, campaign T2 (R13 first), new scam T4.

**Endpoints** (only with `--lab`; absent otherwise):
- `GET /v1/lab/status`: adb path, emulator serial, victim.
- `POST /v1/lab/sms {from, text}`: `adb -s <emu> emu sms send`. The sender is 3 to 15 digits; the
  text is 1 to 480 characters, joined into one line.
- `POST /v1/lab/call {number, action: ring|answer|hangup}`: `adb emu gsm call|accept|cancel`.
- `GET /v1/lab/presets`: messages from `backend/evalsuite/ai_lures.jsonl` (26 scam, 14 everyday),
  plus unknown and saved-contact numbers.
- `GET /v1/lab/workflows`, `POST /v1/lab/workflows/{id}/prepare`, `POST /v1/lab/workflows/{id}/send`.
- `GET /v1/lab/latest?workflow=`: the victim's newest payment, in words.
- `GET /v1/lab/sent`: what the lab sent (sender and length, never the text).
- `POST /v1/lab/reset`: `/sim/reset`, and the lab list is cleared.

**Rules.**
- The lab only plays the *network*. It delivers what the judge typed, or a message from the repo's
  synthetic test set; nothing is generated.
- RUKO still sees only what the phone sends (rule 2). The text stays in the emulator; the lab keeps
  only who sent it and its length, in memory.
- The lab never decides anything (rule 13). Set-up uses the public API like the demo agents, and
  only for other simulated users, never the victim.
- adb runs with argument lists, never a shell, so typed text is not interpreted. `adb emu` works
  only on emulators, never on a real phone.

**Tests:** `backend/tests/test_lab.py` (a fake adb).
