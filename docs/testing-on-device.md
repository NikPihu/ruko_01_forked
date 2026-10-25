# Testing the app on a device (Android Studio)

A checklist for trying every app feature end to end on an emulator or phone, with the server
running on the same laptop. Each test says what to do and what you should see. Tick them off.

To drive a scam from the console instead of typing `adb` commands (a judge plays the scammer, the
victim uses Cache Pay on the emulator), see [features/scam-lab.md](features/scam-lab.md).

## 0. Set up (once)

1. **Get the latest code and start the server.**

   ```powershell
   git checkout main
   git pull
   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 -BaitPump
   ```

   This starts the API and mock intel, pumps the demo mule and the bait account, maps the phone's
   ports to the laptop (`adb reverse`), and adds Meena's contacts to the phone.
   - **Start the emulator first**, so the script finds it.
   - **If the emulator was started later**, run the script again with `-Stop`, then without it.
2. **Install and open the app.** In Android Studio, open the `android/` folder and press **Run**
   (Cache Pay).
3. **Sign in.** Sign up with any details, or log in with passcode `482915` if Meena's account is
   already there. The app always reports as the demo user `u_demo_meena`.
4. **Turn on the switches.** In Profile, switch on everything under safety and allow every
   permission Android asks for:
   - Call signals;
   - App checks;
   - Session checks;
   - SMS scam check;
   - Watch my money alerts;
   - Share suspicious accounts;
   - Check chat messages for scams;
   - Early warnings to Scam Shield.
5. **Open the console** on the laptop: `http://127.0.0.1:8000/console/`. The **Overview → Alert
   health** card and **Transactions** show what the phone sent.

**Commands used below** (in a terminal on the laptop; `adb` is in
`%LOCALAPPDATA%\Android\Sdk\platform-tools`):

| What | Command |
|---|---|
| Send an SMS to the emulator | `adb emu sms send 9876543210 "message text"` |
| Ring the emulator from an unknown number | `adb emu gsm call 9812345670` |
| Answer that call | `adb emu gsm accept 9812345670` |
| Hang up | `adb emu gsm cancel 9812345670` |

The emulator only accepts digits as the SMS sender, so a business header like `VM-HDFCBK` can't be
faked this way. That case is covered by `MessageCheckTest`.

## 1. Alert screens without the server

| # | Do | You should see |
|---|---|---|
| 1.1 | Long-press **Cache Pay** on Home → debug panel → **Preview alert screens** → T1 | A tip on the PIN screen |
| 1.2 | Preview T2 | An explain card; the slide only works after 5 s |
| 1.3 | Preview T3 | Full-screen pause with a 1-minute countdown: call/message trusted person, call 1930, wait, "I know this person". "Pay anyway" appears only after the countdown |
| 1.4 | Preview T4 | "Being checked" screen |
| 1.5 | Switch the profile language to Hindi and repeat 1.3 | The same screen in Hindi |

None of the screens may show a number or score, only words.

## 2. Real payments through the server

| # | Do | You should see |
|---|---|---|
| 2.1 | **To Bank & Self A/c** → `shreeganesh.kirana@okaxis`, ₹150 → Pay | Straight to the PIN, no alert (T0) |
| 2.2 | Debug panel: `on_call` Yes, `caller_in_contacts` No, `remote_access_app` Yes. Then pay `secure.settlement.desk@okaxis` ₹95,000, "Who are you paying?" = Government | T3 pause naming digital arrest, with up to 3 reasons in words |
| 2.3 | On that pause: tap **I know this person** → pick "Friend" → Continue | **Refused:** the pause stays, with the line "Scam Shield still recommends waiting…". The payee is a known mule, so the server says no |
| 2.4 | Tap **Call 1930**, come back, tap **Cancel** | The dialler opens with 1930; the payment is cancelled |
| 2.5 | Console → **Overview → Alert health** | The T3 alert, the actions "called 1930", "cancelled", and "I know this person: 0 accepted, 1 refused" |
| 2.6 | Console → **Transactions** → open the ₹95,000 payment | "Why T3": facts → kinds of evidence → decision |
| 2.7 | App → **History** (bottom bar) | The payment, its payment ID, cancelled, "Looked like: digital arrest" |
| 2.8 | Debug panel: clear overrides, set `call.video` Yes + `on_call` Yes + `caller_in_contacts` No. Pay the mule ₹50,000 | Interrupted (T2 or higher), digital arrest; the console's explanation lists "it is a video call" |
| 2.9 | Debug panel: `session.coached` Yes, then pay the mule | The console's explanation lists "the UPI ID was pasted right after switching from another app" |

**Known model weakness:** with the trained model (`lgbm-0.2`), the plain digital-arrest payment
can come out T1 or T2 instead of T3, and refund QR as T0 (see `docs/ml-asks.md`). If 2.2 shows less
than T3, check the server with the rules scorer before calling it a bug in the app. To do that:
1. Stop the stack: `scripts\dev.ps1 -Stop`.
2. Start the API by hand with `--scorer rules`.

## 3. Message check, scam SMS and OTP warnings

| # | Do | You should see |
|---|---|---|
| 3.1 | `adb emu sms send 9876543210 "Your KYC is pending, your account will be blocked today. Install the app from this link to update."` | Within a few seconds, a notification "This message may be a scam", which names the scam type |
| 3.2 | Tap the notification | The app opens (after the passcode) on **Message check**, with that SMS at the top and a red "Matches a scam script" label |
| 3.3 | `adb emu sms send 9876543210 "Mom, I reached the hostel safely. Will call after dinner."` | No notification; in Message check it shows "No warning signs" |
| 3.4 | `adb emu sms send 9876543210 "482915 is your OTP to log in to NetBanking at your bank. Do not share it with anyone."` (no call going on) | No pop-up; in Message check, a blue "OTP: never share this" label |
| 3.5 | `adb emu gsm call 9812345670`, then `adb emu gsm accept 9812345670`. While the call is on, send the bank OTP SMS from 3.4 (only a UPI or bank OTP gets this warning; an order or delivery OTP does not). Then `adb emu gsm cancel 9812345670` | A notification "A code arrived while you are on a call"; in Message check, that OTP also has the red line "Someone on a call asking for this code is a scammer" |
| 3.6 | Profile language Hindi, repeat 3.1 | Notification in Hindi |
| 3.7 | Switch **SMS scam check** off and repeat 3.1 | Nothing happens; Message check asks you to turn the switch on |

The "Looks AI-written" label stays hidden until the ML `ai_text.json` is in the app's assets.
That is expected.

## 4. Early warnings (sent before any payment)

Needs **Early warnings to Scam Shield** on. After each test, reload the console Overview: the line
under **Alert health** "Early warnings from phones before paying: …" goes up.

| # | Do | Console shows |
|---|---|---|
| 4.1 | Send the scam SMS from 3.1 | "scam messages seen (1)" |
| 4.2 | Send the same SMS again within 30 minutes | No change (same scam type, quiet period) |
| 4.3 | Send a different scam type, e.g. `"Earn Rs 5000 daily by liking videos. Pay Rs 500 to unlock your task level."` | Goes up by one |
| 4.4 | `adb emu gsm call 9812345670` + accept, wait **15 minutes or more**, then cancel | "long calls with unknown callers (1)" |
| 4.5 | Install a screen-sharing app (e.g. AnyDesk from the Play Store, on an emulator image with Play), then close and reopen Cache Pay | "screen-sharing apps installed (1)" |
| 4.6 | Then pay the mule (as in 2.2, but with no overrides) | The console explanation shows the stage reached S3 (under control) before the payment; the app is interrupted |
| 4.7 | Switch **Early warnings** off and repeat 4.3 with yet another scam type | No change in the console |

## 5. Chat message check (WhatsApp, Telegram…)

This needs a chat app that gets real messages, so it is easiest on a **real phone**:
1. Install the debug app.
2. Switch on **Check chat messages for scams** and grant **notification access** (the switch opens
   Android's Settings screen).

| # | Do | You should see |
|---|---|---|
| 5.1 | Ask someone to send you on WhatsApp: "Your KYC is pending, your account will be blocked today. Install the app from this link to update." | "This message may be a scam" notification from Cache Pay |
| 5.2 | A normal WhatsApp message | Nothing |
| 5.3 | With Early warnings on | The console counts it as a scam message seen |
| 5.4 | Remove notification access in Settings | Profile shows "Allow notification access" under the switch |

## 6. Task-scam watcher (money alerts)

| # | Do | You should see |
|---|---|---|
| 6.1 | Debug panel → **Simulate bait credit** twice, then **Simulate outgoing debit** three times (₹1,000, ₹2,400, ₹5,800: each bigger than the last) | A notification pops up; the Alerts screen (tab badge) shows the task-scam card on top |
| 6.2 | Then pay a new UPI ID | Interrupted, task scam; the console shows the episode |

## 7. If something does not work

- **Is the app talking to the server?** Debug panel → "Last request sent" shows the JSON. In the
  console, a new row should appear on Transactions.
- **"Safety check unavailable" on every payment:** the phone can't reach the laptop. Re-run
  `scripts\dev.ps1` with the emulator running (it sets `adb reverse`).
- **No notifications:** Android notification permission for Cache Pay, and the switch in Profile.
- **Server logs:** `logs\api.log` and `logs\api.err.log`.
