# Early warnings and chat message check

**What it does.** Tells the server about risky things before a payment happens. When the user
then pays, RUKO already knows they were contacted, are being guided, or have a screen-sharing app.
Without this, the engine only sees the moment of payment.

**Switches** (Profile and sign-up, both **off by default**, rule 7):
- **Early warnings to Scam Shield** (`Consents.earlyWarnings`): whether anything is sent.
- **Check chat messages for scams** (`Consents.chatLure`): reads new notifications from the chat
  apps in `contracts/watch_rules.json` (WhatsApp, Telegram, Instagram, Messenger, Facebook,
  Truecaller). Android makes the user grant notification access in Settings; the switch opens
  that screen.

**What is sent** (`POST /v1/watch`, contract c2-0.9; only tags and counts, never text, numbers or
contacts, rule 2):

| Warning | When the phone sends it | Also needs | Server stage |
|---|---|---|---|
| `lure_seen` (tag, confidence, `sms` or `notification`, `ai_written`) | a new SMS or chat message matches a scam script with confidence 0.6+ | SMS scam check / Check chat messages | S1 contacted |
| `long_unknown_call` (kind, minutes) | a call of 15+ minutes ends, and the caller is not a contact (or an unseen VoIP caller) | Call checks | S2 hooked |
| `remote_access_on` | a screen-sharing app was installed in the last day (checked when the app opens) | App checks | S3 under control |
| `sideload` | an app from outside the store in the last 24 h | App checks | S3 under control |

**How it works (app).**
- `shield/WatchSender.kt`:
  - `WatchPolicy` turns what the phone saw into an event, or nothing: below the threshold, or
    inside a quiet period (the same scam type is not re-sent within 30 minutes; device warnings at
    most once a day).
  - Events wait in an encrypted file and go out through WorkManager when there is a network.
    Unsent events expire after 7 days.
  - Switching "Early warnings" off deletes the queue.
- **Where sightings come from:**
  - `shield/SmsReceiver.kt` (new SMS);
  - `shield/ChatListener.kt` (chat notifications; the text is checked on the phone and forgotten);
  - `ContextSensor.onCallEnded` (calls);
  - `Signals.reportDevice()` on app start.
- **Shared numbers:** all thresholds are in `contracts/watch_rules.json`, copied to the app's
  assets. The server's tracker (`features/tracker.py`) reads the same file for the 0.6 bar and the
  15-minute long call (rule 6).

**How it works (server).** `features/tracker.py` `observe()` moves the user's stage. The next
`/v1/decide` starts from that stage, so a payment after "unknown long call + screen-sharing app" is
already at S3. The events are stored in `watch_events`.

**Tests:** `WatchPolicyTest.kt` (thresholds, quiet periods, switches, no text fields, the asset
matches the contract copy), and `backend/tests/test_feedback_watch.py` (stages, and that the
server reads the same numbers).
