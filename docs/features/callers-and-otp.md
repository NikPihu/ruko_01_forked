# AI voice at scale and OTP account takeover (c2-0.15)

Two AI-enabled workflows that hit UPI and bank accounts, caught without listening to a call or
reading a message.

## 1. One number, many users (R14)

An AI voice agent (a cloned "bank officer", "police", or a relative in trouble) dials at machine
scale. Each victim alone sees one unknown call; RUKO sees the same number reach many people.

- **Phone:** when a call of `long_call_min`+ minutes from a non-contact SIM number ends, the
  `long_unknown_call` early warning carries `caller_hash`: the number as a salted SHA-256 pseudonym
  (`Handles.wireValue("phone", …)`, the same hash as a call-back number in scam messages). Never the
  number. VoIP calls have no number, so no hash (unknown, rule 1).
- **Server:** `graph/campaigns.py` `CampaignStore.record_call` counts the **different** users each
  number reached (these warnings plus payments made on a call with a non-contact caller).
  `policy.yaml campaign: caller_window_hours` (24) and `caller_min_users` (3).
- **At payment time:** a payment on a call from such a number gets `caller_many_users` = true (call
  family, `features/build.py`), reason `R14_caller_many_users` (rules scorer, and the evidence overlay
  for the trained model). Unknown number → null. It is call evidence only, so it interrupts only with
  a second family (rule 5).
- **Console:** Overview → "Spreading now" lists such numbers as "Caller (calls)" (pseudonym hidden).

## 2. An OTP during an unknown call (R15, playbook `otp_takeover`)

The caller (often an AI voice posing as the bank) triggers a login, a SIM swap or a new device
registration and asks for the code. That is an account takeover in progress, in UPI or net banking.

- **What the OTP is for** (`MessageCheck.otpPurpose`, on the phone): a bank's or a UPI app's sender
  header decides (`VM-HDFCBK` → bank, `AX-PHONPE` → UPI); otherwise UPI words (UPI PIN, VPA, BHIM,
  Google Pay, PhonePe, Paytm, collect request) → UPI; words for orders, deliveries and social apps
  (Swiggy, Amazon, Instagram, …) → other; bank words (NetBanking, a/c, beneficiary, card, NEFT/IMPS,
  बैंक, खाता) → bank; nothing → unknown. **Only UPI and bank OTPs are acted on.** An OTP for an order or
  a social app on a call still gets "never share this" in Message check, but no takeover warning and
  no report.
- **Phone:** for a UPI or bank OTP during a call, `SmsReceiver` warns the user ("SMS scam check" +
  "Call signals" on) and, with "Early warnings" on, queues the `otp_during_call` early warning: the
  purpose (`upi` / `bank`), call type and `caller_hash` only, never the code, the sender or the text
  (rule 2). A saved contact's call is not reported.
- **Contract:** `otp_purpose` is required on `otp_during_call` and must be `upi` or `bank`; anything
  else gets 422.
- **Server:** the stage tracker counts it as contact and control (stage S3) and remembers it for
  `watch_rules.json otp_recent_min` (120) minutes. A payment in that time gets `otp_on_call` (call
  family), reason `R15_otp_on_call`, and the playbook `otp_takeover` (app words
  `t2_otp_takeover` / `t3_otp_takeover`, English and Hindi). The OTP also counts the caller for #1.
- No report is not proof of no OTP: the feature is true or null, never false (rule 1).

## Try it

- Demo agents (Overview → Run scenario): `voice_clone_caller` (four users report a long call from
  the same number, a fifth pays on a call from it → T2+ with R14) and `otp_takeover` (OTP during a
  call, then ₹25,000 to a new account → T2+, `otp_takeover`, R15).
- Tests: `backend/tests/test_caller_crowd_otp.py`, `android/.../shield/WatchPolicyTest.kt`.
