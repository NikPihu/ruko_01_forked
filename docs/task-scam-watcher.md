# Task-scam watcher: plan (contract c2-0.3)

Status: **design only, not built yet.** This file is the full brief for building it on any machine.
It covers the phone (UI + background watcher), the contract, the engine and the data.

## 1. Why

The task / job scam ("like videos, earn ₹500 a day") and the trading-group scam work like this:

1. Small "rewards" come in from strangers.
2. The victim pays a stranger to "unlock" earnings.
3. Each payment is bigger than the last, often to a **different payee** each time.
4. After days or weeks the scammers vanish.

Since c2-0.2 the phone sends a 72-hour money summary (`context.money`) with every Pay tap. That has
three problems:

- **Too short and too late.** The pattern spans many payees and up to weeks, and it is only
  looked at when the user taps Pay in *this* app. Payments made in GPay or PhonePe are never
  watched as they happen.
- **One source lights two families.** Bait (lure family) and escalation (behaviour family) both
  come from the same phone money summary. With the +1.5 `TASK_WORKFLOW_BONUS` this can reach T2
  with no independent evidence, which breaks CLAUDE.md rule 5.
- **Training and evaluation can't use it.** These features exist only in the live engine; nothing
  rebuilds them from the simulated ledger.

**New design.**
- The phone runs a **background episode watcher**. From the moment Scam Shield is switched on, it
  tracks the money flow across all payees for up to 30 days, even when the app is closed.
- It warns the user early by itself, with gentle notifications only.
- At payment time it sends **one episode summary**. The engine counts that summary as a
  **single signal in the lure family**. Any interruption (T2 or higher) still needs a second,
  independent family: a mule-like payee, or an amount that is unusual for this user.

## 2. What the watcher reads

**Yes: it watches bank SMS alerts and the user's own payment history.**

| Source | What it gives | Why |
|---|---|---|
| **Bank SMS alerts** (credited / debited) from bank sender IDs such as `AX-HDFCBK` | Money **in** (the bait) and money **out** from *any* UPI app | The only place the phone sees credits, and payments made in other apps |
| **This app's own payment history** (`AccountStore.loadPayments()`) | Money out, with the exact payee UPI ID | Exact payee, and no dependence on SMS |
| Lure SMS (optional, existing `LureClassifier`) | "task", "earn per day", "recharge to withdraw" | Supporting signal; not needed for an episode |

Rules that stay as they are:
- SMS text is parsed on the phone and **thrown away immediately**. Only `{ts, amount, in/out,
  counterparty UPI ID if named, source}` is kept, encrypted, for 30 days.
- A "credited" SMS from a **phone number** (not a bank sender ID) is not counted. That is itself a
  scam trick. Existing code: `BankSms.trustedSender`.
- A payment made in this app also arrives as a debit SMS; count it once. Existing code:
  `MoneyFlow.dedupe`.
- OTPs, collect requests, cashback, refunds and reversals are ignored. Existing code:
  `BankSms.SKIP`.

**Definition of a bait credit:** money in of **₹500 or less** from a counterparty the user has
**never paid** in their 30-day history, or with no counterparty named in the SMS.

## 3. The episode (same definition on phone and server)

One episode per user. It starts at the first bait credit.

```
          bait credit                        2+ payments out to new payees after the first bait
 NONE ─────────────────► WATCHING ─────────► ACTIVE    and escalation_steps >= 2
  ▲                         │                  │       (each payment >= 1.5x the one before)
  │      30 days with no    │                  │
  └──── bait and no out ◄───┴──────────────────┘
                            │                  │
                            └── user taps "I know them / this is a real job" ──► DISMISSED
                                (stays DISMISSED for 30 days or until a NEW bait sender appears)
```

Counters kept per episode. "Out" means payments out *after the first bait*.

| Field | Meaning |
|---|---|
| `age_days` | Days since the first bait credit |
| `bait_credits`, `bait_inr` | Number and total of bait credits |
| `outs`, `outs_inr` | Payments out, from any app |
| `new_payees` | Distinct payees paid for the first time during the episode |
| `escalation_steps` | Run of outs, ending with the latest, where each is ≥ 1.5× the previous |
| `last_out_inr` | The latest payment out |
| `out_to_in_ratio` | `outs_inr / bait_inr`. Null when credits can't be seen. |

**All thresholds go in one config file, `contracts/episode_rules.json`.** The phone copies it into
`android/app/src/main/assets/` and Python reads it from `contracts/`. Neither side hard-codes
numbers.

```json
{ "version": "episode-0.1", "bait_max_inr": 500, "escalation_factor": 1.5,
  "active_min_outs": 2, "active_min_escalation_steps": 2,
  "quiet_close_days": 30, "history_days": 30, "same_payment_minutes": 10 }
```

**Phone and server must agree.** Write `contracts/examples/episode_vectors.json`: a list of test
cases, each a timeline of transactions plus the expected state and counters. The Kotlin unit test
and the Python test both run every vector. Include at least:
- a classic task scam (bait ×3, then 1k → 2.5k → 6k);
- bait with no payments out (stays WATCHING);
- escalating payments with no bait (stays NONE);
- cashback SMS (ignored);
- a credit SMS from a phone number (ignored);
- a dismissed episode, then a new bait sender (back to WATCHING);
- a 30-day quiet period (back to NONE);
- an app payment plus its debit SMS (counted once).

## 4. Android: background tracking when the shield is on

### 4.1 Turning the shield on and off
- One switch, **"Watch my money alerts"**. It needs the SMS consent and lives in sign-up and
  Profile next to the existing three. Add `moneyWatch` to `Consents` in `data/AccountStore.kt`.
- **Turning it on:**
  1. Ask for `RECEIVE_SMS`, `READ_SMS` and, on Android 13+, `POST_NOTIFICATIONS`. Extend
     `ShieldPermissions` and `ShieldPermissionCard`.
  2. Enable the SMS receiver with `PackageManager.setComponentEnabledSetting`. It ships disabled.
  3. Schedule the periodic catch-up worker.
  4. Run a **backfill**: read the last 30 days of SMS once and build the episode from them.
- **Turning it off:** disable the receiver, cancel the work, and **delete** the stored money
  history and episode.

### 4.2 Running when the app is closed (no permanent foreground service)
| Piece | How it runs | Job |
|---|---|---|
| `shield/SmsReceiver` | Manifest receiver for `android.provider.Telephony.SMS_RECEIVED` (`android:permission="android.permission.BROADCAST_SMS"`, `exported="true"`, `enabled="false"`). This broadcast is on Android's exempt list, so it **wakes the app even when it isn't running**. | Read the PDUs with `Telephony.Sms.Intents.getMessagesFromIntent`. If the sender is a trusted bank, parse it with `BankSms.parse` and hand the transaction to `EpisodeWorker`. Otherwise optionally classify it as a lure. Never store the text. |
| `shield/EpisodeWorker` | WorkManager `OneTimeWorkRequest`, expedited | Apply the transaction to the episode, save it, and post a notification if the state changed |
| `shield/CatchUpWorker` | WorkManager `PeriodicWorkRequest`, every 6 h | Re-scan the SMS inbox since the last scan, to cover missed broadcasts, reboots and force-stops. Close quiet episodes. |
| Payment in this app | `PaymentViewModel`, after success | Feed the app's own payment into the episode |

- Add `androidx.work:work-runtime-ktx`; it is already in the CLAUDE.md stack. WorkManager keeps its
  schedule across reboots by itself.
- **Don't use a foreground service.** It isn't needed, it shows a permanent notification, and
  Android 14 and 15 limit them.
- **Limits to tell the user about:**
  - After a **force-stop**, Android blocks all of the app's receivers until the user opens it
    again.
  - On Xiaomi, Oppo, Vivo and Realme, "autostart" or battery optimisation may need to be allowed.
    Add a "Keep Scam Shield running" help row in Profile that opens
    `Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS`.
- **Play Store policy:** SMS permissions are allowed only for default SMS apps or approved
  exceptions, so this is a **demo build feature**. It is already noted in the manifest. The
  production route is the bank or PSP's own transaction feed, or Account Aggregator.

### 4.3 New code (package `com.ruko.demo.shield`)
- **`EpisodeTracker.kt`:** pure Kotlin with no Android imports, so it is unit-testable. It holds
  the state machine from §3 and reads `episode_rules.json`. It replaces `MoneyFlow.summarise` for
  the request. Keep `BankSms` and `dedupe`.
- **`EpisodeStore.kt`:** encrypted with the existing `SecureStore`. It holds:
  - the money transactions (30 days);
  - the episode state;
  - the last SMS scan time;
  - a log of notifications already shown.
- **`ShieldController.kt`:** on/off, permissions, receiver enable/disable, work scheduling,
  backfill, delete.
- **`SmsReceiver.kt`, `EpisodeWorker.kt`, `CatchUpWorker.kt`:** as in the table above.
- **`ShieldNotifier.kt`:** a notification channel "Scam Shield alerts", with Hindi and English
  text.

### 4.4 What the phone does by itself (no server, never blocks a payment)
| Moment | Action |
|---|---|
| NONE → WATCHING | One notification: "Got ₹150 for a 'task'? Real jobs never ask you to pay to get your earnings." / "‘टास्क’ के लिए ₹150 मिले? असली नौकरी कमाई पाने के लिए पैसे नहीं माँगती।" |
| WATCHING → ACTIVE | Notification plus a Home banner: "You received ₹450 from 3 unknown accounts and then paid ₹9,500 to 4 new people, each time more. This is how task scams work. Stop before paying more." |
| A debit SMS from **another app** while ACTIVE | Notification after the fact: "You just paid ₹6,000. The next ask will be bigger. Don't pay more." |
| Limit | At most one notification per state change, and at most 2 per week |

### 4.5 UI changes
- **Home** (`ui/HomeScreen.kt`):
  - A shield status chip: "On, watching money alerts" or "Off".
  - An **episode card** when the state is WATCHING or ACTIVE, showing:
    - the numbers, in words;
    - a "How this scam works" sheet;
    - buttons **Call 1930**, **Call my trusted contact** (`UserProfile.trustedMobile`) and
      **"I know them / it's a real job"** (sets the state to DISMISSED).
- **Profile** (`ui/auth/ProfileScreen.kt`): a "Watch my money alerts" switch, a "Keep Scam Shield
  running" help row, and a "Delete money history" button.
- **Sign-up consent** (`ui/auth/SignUpScreen.kt`): one line explaining background watching and
  that SMS text never leaves the phone.
- **Decision screen** (`ui/DecisionScreen.kt`): text specific to the task scam for `message_key`
  values `t2_task_job` and `t3_task_job`.
- **Debug panel** (`ui/DebugPanel.kt`):
  - "Simulate bait credit" and "Simulate outgoing debit" buttons that feed fake transactions;
  - the current episode state and counters;
  - "+1 day" to test the 30-day close.

  The existing `taskMoney` override is replaced by these.
- **Strings:** all new text goes in `values/` and a new `values-hi/`.

### 4.6 The request at payment time
`Signals.read()` sends `context.episode` built from `EpisodeStore`, instead of computing
`context.money` again.
- If the shield is on but SMS is off: `bait_credits`, `bait_inr` and `out_to_in_ratio` are
  **null**, never 0.
- If the shield is off: `episode` is **null**.

## 5. Contract c2-0.3 (`backend/schema/events.py`, the source of truth)

```python
class EpisodeSignal(_M):
    """Task-scam episode kept on the phone across payees for up to 30 days (c2-0.3)."""
    state: Literal["none", "watching", "active", "dismissed"]
    age_days: Optional[float] = Field(None, ge=0)          # since first bait credit
    bait_credits: Optional[int] = Field(None, ge=0)        # null when SMS can't be read
    bait_inr: Optional[float] = Field(None, ge=0)
    outs: Optional[int] = Field(None, ge=0)                # after first bait, any app, excl. this payment
    outs_inr: Optional[float] = Field(None, ge=0)
    new_payees: Optional[int] = Field(None, ge=0)
    escalation_steps: Optional[int] = Field(None, ge=0)
    last_out_inr: Optional[float] = Field(None, gt=0)
    out_to_in_ratio: Optional[float] = Field(None, ge=0)
    payee_seen_in_episode: Optional[bool] = None           # this payee already paid in this episode
    rules_version: Optional[str] = None                    # e.g. "episode-0.1"

class Context(_M):
    ...
    money: Optional[MoneySignal] = None      # c2-0.2, deprecated: still accepted in c2-0.3, removed in c2-0.4
    episode: Optional[EpisodeSignal] = None  # c2-0.3
```

- Set `CONTRACT_VERSION = "c2-0.3"`, then run `python -m schema.export`.
- Add `contracts/examples/decide_request_task_episode.json`. Keep the c2-0.2 `money` example, so
  the test proves old requests still validate.
- Update `contracts/README.md` and its changelog. Mirror the change in Android
  `net/Models.kt` and `ContractTest.kt` in the same change (CLAUDE.md rule 8).

## 6. Engine changes (`backend/`)

- **`features/episode.py` (new):** the same state machine as `EpisodeTracker.kt`, in Python, reading
  `contracts/episode_rules.json`. It is used offline to rebuild episodes from the ledger. The
  online engine trusts the phone's summary.
- **`features/build.py`:**
  - New features: `episode_state` (0 none, 1 watching, 2 active, 3 dismissed), `episode_age_days`,
    `episode_bait_credits`, `episode_new_payees`, `episode_out_to_in`, and
    `episode_escalation_steps`.
  - The last one is +1 if this payment is ≥ 1.5× `last_out_inr`, otherwise 0.
  - **All `episode_*` features belong to family L only.**
  - Remove the c2-0.2 money features, or map `money` onto them while it is still accepted.
- **`api/rule_scorer.py`:**

  | Episode state | Effect |
  |---|---|
  | ACTIVE | Family L 0.85, reason `R10_bait_then_pay` |
  | WATCHING, with a first-time payee | Family L 0.5 |
  | DISMISSED | No L signal, unless the payee has an intel hit (the same override as "I know this person" in `policy.yaml`) |

  Also:
  - **Delete `TASK_WORKFLOW_BONUS`.** Escalation that comes from the episode must not light the
    behaviour family.
  - Set the playbook to `task_job` when the episode is ACTIVE.
  - Bump the model version to `rules-0.3`.
- **`features/tracker.py`:** replace the bait-credit logic. An episode in WATCHING counts as
  contact (S1); ACTIVE counts as hooked (S2) at least. `minutes_since_first_contact` can use
  `age_days`.
- **Expected outcomes, each with a test:**

  | Situation | Expected |
  |---|---|
  | ACTIVE + clean payee + normal amount | **T1 at most** (single family) |
  | ACTIVE + mule-like payee | T2 or T3, playbook `task_job` |
  | ACTIVE + amount far above the user's 90-day max | T2 |
  | WATCHING alone | T0 or T1 |
  | DISMISSED + payee on the I4C registry | Still alerts |
  | A c2-0.2 `money` request | Still accepted |

- **Known gap:** the behaviour family's amount baseline only exists for simulated users. Real phone
  users get an empty baseline, so the payee family is the realistic second family in a live demo.

## 7. Data and evaluation (`data/sim/`)

- **Offline features:** for each payment in `ledger.parquet`, rebuild the user's episode as of that
  moment with `features/episode.py`. Use credits from the ledger (including `scam_bait` flows) as
  "bank SMS" for users who have SMS consent, and null for those who don't. Feed the results into
  the training table.
- **Simulator additions:**
  - an SMS-consent flag per user (for example 60%);
  - payees that rotate after every payment;
  - victims with no bait (crypto "deposit" variant);
  - **hard negatives**:
    - merchant cashback (should be ignored);
    - a friend repaying a small loan;
    - real gig payouts (regular, from a known payer);
    - a user paying several new shops while travelling.
- **Evaluation chart:** task-scam rupees stopped and the alert moment (which payment number) for
  three setups: existing stack only, + episode (phone), and + episode + payee intel.

## 8. Build order and done checks
1. **Contract and rules.**
   - Write `episode_rules.json`, `episode_vectors.json`, `EpisodeSignal`, the c2-0.3 export and the
     examples.
   - Done when `pytest backend/tests` passes and the c2-0.2 example still validates.
2. **Python `features/episode.py`.** Done when all vectors pass.
3. **Engine** (scorer, build, tracker). Done when the outcome table in §6 passes as tests.
4. **Android `EpisodeTracker` and `EpisodeStore`.** Done when the Kotlin unit test passes the same
   vectors.
5. **Android background pieces:** receiver, workers, `ShieldController`, notifier, manifest,
   WorkManager dependency.
   - Done when, with the app swiped away, an emulator SMS updates the episode and posts a
     notification.
   - Emulator test: `adb emu sms send 5554 "Rs 150 credited to a/c XX12 by task.reward@ybl UPI"`.
     Debug builds accept numbered senders.
6. **Android UI:** Home episode card, Profile switches, Decision text, Debug panel, Hindi strings.
7. **Data:** offline episodes, simulator additions, and the evaluation chart.

## 9. Privacy checklist (must stay true)
- [ ] SMS text is never stored or sent; only parsed amount, direction, counterparty and time.
- [ ] Money history is encrypted on the phone, kept 30 days, and deleted when the switch goes off.
- [ ] The server receives only the episode summary, and only when the user taps Pay.
- [ ] Unmeasured fields are `null`, never 0 or false.
- [ ] The phone only warns; it never blocks a payment. Payment-time interruptions stay with the
      engine, which needs two families.
- [ ] Age and gender are not used anywhere in the episode logic.
