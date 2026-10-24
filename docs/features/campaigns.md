# Same scam, many phones (scam campaigns) and new accounts spreading fast

**Why.** AI crews reword their scam message for every victim and burn a fresh mule account every
few victims. Registries lag days behind: I4C lists an account after complaints, DoT FRI refreshes
daily, MuleHunter scores nothing under 7 days old. So a new mule looks clean exactly when it is most
active. RUKO sees many users in real time, and the crew must reuse what moves money: the UPI ID to
pay, the link to open, the number to call back. RUKO counts those across phones within minutes.

## 1. Same scam, many phones (contract c2-0.13)

**On the phone** (`signals/Handles.kt`, `signals/MessageCheck.kt`):
- When the scam check flags a message (SMS or chat notification), the app finds its money handles:
  - UPI IDs;
  - link hosts;
  - call-back numbers.
- They go with the `lure_seen` early warning (`WatchEvent.handles`, at most 10). The message text
  never leaves the phone (rule 2):
  - the UPI ID is sent plain, as payees always are (rule 7);
  - a link host or number is sent as `sha256:<hex>` of the salted, normalised value. That is
    pseudonymisation, not secrecy.
- An email, an amount, "a.m.", "Mr.Sharma", an OTP or a date is never a handle. OTP messages carry
  no handles.
- The same scam type is quiet for 30 minutes, but a message with **new** handles is still reported.
- The phone and server normalise and hash identically, checked by both against
  `contracts/examples/handle_vectors.json`.
- Needs "Early warnings" (off by default) plus "SMS scam check" or "Check chat messages".

**On the server** (`backend/graph/campaigns.py`):
- `/v1/watch` records each handle per user.
- A handle that reached **3 different users within 60 minutes** is *spreading*
  (`policy.yaml campaign:`). One phone getting the same scam many times counts once.
- At `/v1/decide`:
  - `payee_in_campaign`: the payee UPI ID is spreading (payee family P);
  - `caller_in_campaign`: the caller's number, hashed the same way, is a spreading call-back number
    (call family C).
- **One campaign is one source of evidence**, so it lights at most one family: the payee, or the
  call only when the payee doesn't match (rule 5).
- Reason **R13_scam_campaign**, in the user's words: "This account is being sent to many people in
  scam messages right now" (English and Hindi).

## 2. New and spreading (#3)
- RUKO records when it first sees each account.
- An account first seen within **48 h** that **3+ different users** already pay is
  `payee_new_and_spreading` (P, reason R3, `policy.yaml crowd:`).
- Excluded: verified merchants, and accounts the bank says are over 30 days old. Unknown age still
  counts (rule 1).
- The older crowd thresholds moved from code into `policy.yaml crowd:` (rule 6).

## Works with the trained model, never alone
The live scorer `lgbm-0.2` was never trained on these features. `api/overlay.py` applies them after
any scorer:
- the feature lifts its family to 0.6 and puts its reason first;
- the policy raises the tier to **T2** (explain card, slide to pay) only when **another family is
  also lit**.

On its own this evidence never interrupts (rule 5). Settings: `policy.yaml evidence_overlay:`.

## Console
**Overview → "Spreading now"**: each handle going around in the last hour, how many people got it,
first and last seen. UPI IDs are shown plain; links and numbers stay "hidden (pseudonym only)".
API: `GET /v1/campaigns/spreading`.

## Checked live (lgbm-0.2, curl as the phones)
| Case | Result |
|---|---|
| Three phones got three differently worded scams with the same UPI ID; a fourth user who also got a scam pays it | **T2**, reason R13 first |
| A real user with payment history pays ₹300 by QR to that UPI ID, nothing else seen | **T0** (rule 5) |
| A handle only one phone ever saw | **T0**, no R13 |

## Tests
- Backend:
  - `tests/test_campaigns.py`: vectors, distinct users, window, the engine, one family per
    campaign, the console endpoint;
  - `tests/test_velocity.py`;
  - `tests/test_schema.py` (c2-0.13).
- Android:
  - `HandlesTest`: shared vectors, AI-style and Hinglish messages, ordinary text, the cap;
  - `WatchPolicyTest`: handles in the event, new handles not silenced.

## Next (not built)
- **Diwansu:** retrain on the new features (`lgbm-0.3`) with a non-negative combiner.
- **Nikunj:** AI-variant red-team playbooks (rephrased message, same UPI; fresh mule every few
  victims). Then measure the miss rate before and after with `interface_script`.
- **Caller crowd (#2):** one unknown number calling many RUKO users.
