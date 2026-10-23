# RUKO flows: what happens, in order

Plain-language walk-throughs of the main flows. Each step names the file that does it. Details
of each feature are in [`features/`](features/README.md); the rules (rule 1 to 14) are in the
root `CLAUDE.md`; the request and response shapes are in `contracts/README.md`.

## 1. Before any payment: the phone watches (on the phone)

All of this runs on the phone and only with the matching switch on. Nothing is shown to the user
unless there is a pattern (rule 10), and no message text, call audio or contact ever leaves the
phone (rule 2).

1. **A new SMS arrives.** `shield/SmsReceiver.kt`:
   - **Bank alert** ("Watch my money alerts"): parsed into amount, direction and UPI ID. It feeds
     the task-scam watcher (`shield/EpisodeTracker.kt`), which spots "small rewards in, bigger
     payments out". If "Share suspicious accounts" is on, a state change goes to `POST /v1/episode`.
   - **Any other SMS** ("SMS scam check"): checked by the lure model. A scam script gets the
     "This message may be a scam" notification.
   - **An OTP during a call** gets the full "never share this code" warning.
2. **A chat notification arrives** (WhatsApp, Telegram...; "Check chat messages" plus Android's
   notification access). `shield/ChatListener.kt` checks it the same way.
3. **A call ends.** If it lasted 15+ minutes with someone unknown, `ContextSensor` reports it.
4. **The app opens.** A screen-sharing app installed in the last day, or an app from outside the
   store, is noted.
5. **With "Early warnings" on**, items 1 to 4 become tags sent to `POST /v1/watch`. This goes
   through `shield/WatchSender.kt`: an encrypted queue, with quiet periods from
   `contracts/watch_rules.json`. The server's stage tracker (`features/tracker.py`) moves the
   user's scam stage forward: S1 contacted, S2 hooked, S3 under control.

## 2. One payment, from Pay to the console

1. **Pay.** The user enters a UPI ID or number and an amount in Cache Pay. The phone takes one
   reading (`signals/Signals.kt`), sends it to `POST /v1/decide`, and gives up after 1 s (rule 3).
   The reading has:
   - the call;
   - the device (remote access, sideloads);
   - scam message tags from the last 72 h;
   - the task-scam episode summary;
   - how the Pay screen was used;
   - whether the payee is a saved contact;
   - the on-device model's verdict.
2. **The engine decides** (`backend/api/main.py` `decide_inner`), within 200 ms or it answers T0
   `fail_open`:
   1. **Stage tracker:** where this user is in a scam journey.
   2. **Payee intel, in parallel, 150 ms budget** (`api/intel.py`): mock NPCI, bank risk and money
      flows, DoT FRI, the I4C registry, plus the payment graph (crowd signal, money loop,
      bot-scale ring, analyst-approved mules).
   3. **Features** (`features/build.py`), each in one family: C context, L lure, P payee,
      B behaviour.
   4. **Scorer:** `lgbm-0.2` by default (the trained model in `ml/`), or `rules-0.7` if it can't
      load. The result is a scam probability, family scores and reasons.
   5. **Scam type:** the playbook from `data/playbooks/playbooks.yaml` (`api/playbooks.py`).
   6. **Policy** (`api/policy.py` + `policy.yaml`):
      - two families must be lit for T2+ (rule 5);
      - amount caps;
      - trusted payees;
      - the alert budget.

      The result is a tier T0 to T4, a message key and pause minutes.
3. **Records, off the payment's path:**
   - an evidence record (`evidence/store.py`, hash-chained);
   - the full decision in the transaction database (`store/db.py`);
   - the payment in the payment graph (`graph/store.py`).
4. **The app shows the answer** (`ui/alerts/`), in words, in English or Hindi, never the score
   (rule 4):

   | Tier | Screen |
   |---|---|
   | T0 | nothing |
   | T1 | a tip on the PIN screen |
   | T2 | an explain card: read for 5 s, then slide to pay |
   | T3 | a full pause: countdown; call or message your trusted person; call 1930; wait with a reminder; "I know this person" |
   | T4 | "being checked" |
   | no answer | "safety check unavailable", the user can still pay |

5. **What the user does on the alert** goes to `POST /v1/feedback` (`PaymentViewModel.onAlertAction`).
   For "I know this person", the server decides: it refuses if the payee or caller is listed,
   someone may control the phone, or the payee looks like a mule. If it refuses, the pause stays.
6. **PIN or Cancel.** The outcome goes to `POST /v1/payment/outcome`. History merges the phone's
   record with the server's (`GET /v1/me/payments`).
7. **The analyst sees everything** on the console (`/console/`):
   - **Transactions:** the payment.
   - **Payment explanation:** every score, every reason with its inputs, every playbook checked,
     the policy steps and the sources.
   - **Alert health:** what users did on alerts.

## 3. After payments: finding the people behind the scams

1. **Mules and rings.** `graph/discover.py` ranks suspect accounts from the payment graph. It groups
   them into rings (shared victims, money between them) and finds hubs (many payers, money passes
   straight through). Bot-scale rings are tagged: the same amount from many people at a steady
   rhythm (`graph/store.py` `automation`). Console pages: **Suspects**, **Scam rings**.
2. **Humans approve** (rule 11). A discovered suspect affects live payments only after two different
   analysts approve it on the Suspects page. After that, paying it lights the payee family (P).
3. **New scam workflows.** `patterns/emerging.py` groups recent flagged payments that matched no
   playbook by how they happened: call, message, control, Pay-screen signs, entry, amount. A group
   from several people that keeps growing is listed on **Emerging patterns**. An analyst names it,
   which drafts a playbook entry in the file's format. The data owner adds it to
   `data/playbooks/playbooks.yaml`, and from the next start the engine names that scam type.

## 4. Demo: every scam type, live

`python -m demo.agents --all` (or **Run scenario** on the console Overview) runs scripted people
through the real API: a victim of each scam type, honest users, and a hidden scam type with no
playbook. Each does what a person would do: early warnings, episode events, the payment check,
alert actions, the outcome. It prints what RUKO did against what should happen. The hidden one
shows up on Emerging patterns, and its mule as a bot-scale ring. See
[`features/demo-agents.md`](features/demo-agents.md).
