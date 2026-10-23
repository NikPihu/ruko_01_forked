# Alert screens (T1 to T4) and feedback

**What it does.** Shows the engine's answer at payment time, and tells the server what the user
did. RUKO warns and pauses; it never hard-blocks a payment (rules 3, 10).

**Screens** (`android/.../ui/alerts/`, English and Hindi, in the profile's language):

| Tier | Screen | What the user can do |
|---|---|---|
| T1 | `TipBanner` on the PIN screen | read it, pay |
| T2 | `ExplainCard` | read for 5 s (read gate), then `SlideToConfirm` to pay, or cancel |
| T3 | `PauseScreen`: a full-screen countdown (`pause_minutes`) | call or message their trusted person (the SMS has no amount or payee); call 1930; wait (`PauseReminder` reminds them when the pause ends); "I know this person"; after the pause, "Pay anyway" |
| T4 | `ReviewScreen` | "being checked"; same actions as T3 |
| none | `UnavailableScreen` | the check failed or timed out ("safety check unavailable"); the user can still pay |

**Feedback** (`POST /v1/feedback`, contract c2-0.9):
- Every tap on an alert goes through `PaymentViewModel.onAlertAction`, in the background: slid to
  pay, cancelled, waited, called trusted, messaged trusted, called 1930, paid after pause,
  "I know this person" with why.
- The server (`backend/api/feedback.py`) checks the payment belongs to the user and limits it to 30
  a day. A retry with the same `feedback_id` gets the same answer.
- **"I know this person" is decided by the server.** It is refused (`know_them_not_accepted`) when
  the payee or caller is on a list, someone may be controlling the phone, or the payee family (P)
  is lit. If refused, the pause stays and the screen says why. A scammer can tell a victim to tap
  it, so the phone alone never lifts a pause.

**Alert health** (`GET /v1/metrics/alerts`, console Overview card), numbers only:
- for each tier: how often it was shown, the share completed and cancelled, the median time on the
  alert, and the actions taken;
- interruptions per 1,000 checks;
- "I know this person" accepted vs refused;
- scam messages seen before paying, and how many looked AI-written.

**Try it.** In the app, long-press "Cache Pay" on Home, then **Preview alert screens**. Each
screen opens with a sample answer, without the server.
**Tests:** `AlertsTest.kt`, `backend/tests/test_feedback_watch.py`.
