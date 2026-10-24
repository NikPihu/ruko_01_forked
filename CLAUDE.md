# CLAUDE.md: working in ruko_01

RUKO (रुको) is a UPI scam workflow shield for the Amazon AI Cyber Security Hackathon, Track 02:
pause the scam, not the payment. All data is synthetic or public. Finale around 2026-11-07.
Start with `README.md` (owners, layout, run commands); this file is the rules and the map.

## Who owns what

| Folder | Owner | What lives there |
|---|---|---|
| `android/` | Manjeet Singh | Cache Pay, the Kotlin + Compose app (`com.ruko.demo`) |
| `backend/` | Jagdeep Singh | Risk API, stage tracker, features, policy, evidence vault, mock intel, payment graph, shared schema |
| `console/` | Jagdeep Singh | Analyst console (React + TypeScript), served by the API at `/console/` |
| `ml/` | Diwansu Pilania | Training replay, the LightGBM server scorer (`model/predict.py`), the on-device model (`device_model.json`), the lure classifier (`lure.json`); plan and status in `ml/PLAN.md` |
| `data/` | Nikunj Santosh Tangle | Simulator (`sim/`), evaluation (`eval/`), generated datasets |
| `contracts/` | shared | Published contract, generated from `backend/schema/events.py` |
| `docs/` | shared | `flows.md` (what happens, in order), `features/*.md` (one page per feature), `ml-asks.md`, design briefs (`task-scam-watcher.md`) |

Branches: `android/*`, `backend/*`, `ml/*`, `data/*`, or `feature/*` for cross-folder work.
Merge to `main` by pull request. Keep `main` runnable.

## Rules

The rule numbers are cited elsewhere (`docs/`, `contracts/README.md`); keep them stable.

1. **Unknown is never safe.** A signal the phone or a service could not measure is `null` (or left
   out), never `false` or `0`. Applies to the request, features, scorer and evaluation.
2. **Only conclusions leave the phone.** No SMS text, audio, contacts or screen content is sent.
   The phone sends derived flags and counts. SMS text is parsed on the phone and thrown away.
3. **Fail open.** `/v1/decide` answers in 200 ms or less or returns `fail_open` (T0). The app gives
   up after its own 1 s timeout and treats a timeout, an error or a 422 as "safety check
   unavailable". A payment is never hard-blocked by RUKO failing.
4. **The user never sees a score; the analyst sees everything.** Since c2-0.8 the response carries
   `threat` (a 0–100 score, a level that always follows the tier, the scam type, the lit families).
   The app shows only the level and scam type in words, plus the top 1–3 reasons (English and
   Hindi); never the number (a scammer holding the phone could probe it). The analyst console
   shows every number: `threat.score`, `p_scam`, family scores and each input's push
   (`GET /v1/payments/{id}/explain`).
5. **Two independent families before interrupting.** Families are C context, L lure, P payee,
   B behaviour. T2 or higher needs at least two lit families (`api/policy.yaml`
   `corroboration_min_families`). One source of evidence must never light two families: the whole
   phone episode (`context.episode`) is one L signal, and graph / crowd signals are P only.
6. **Thresholds live in config, not code.** Policy numbers in `backend/api/policy.yaml`; episode
   numbers in `contracts/episode_rules.json` (the phone copies it to
   `android/app/src/main/assets/`, and `EpisodeTrackerTest` checks the copy); early-warning numbers
   in `contracts/watch_rules.json` (same copy, checked by `WatchPolicyTest`; the server's tracker
   reads it too).
7. **Privacy by default.** Phone data is AES-256-GCM encrypted with an Android Keystore key in
   `noBackupFilesDir`, excluded from backup; "Delete my data" removes the files and the key. RUKO
   users are pseudonymised on the server (`evidence/store.py` `pseudonym()`); payees, bait senders
   and cash-out accounts stay plain because they must be looked up. New consents default to off,
   with one exception: "Session checks" (`Consents.sessionSignals`, c2-0.5) is on by default,
   because it sends only counts and rounded times measured inside RUKO's own Pay screen (never
   keys typed or which other app was open) and the user can switch it off.
8. **A contract change is one change everywhere.** Edit `backend/schema/events.py`, bump
   `CONTRACT_VERSION`, run `python -m schema.export`, update `contracts/examples/` and
   `contracts/README.md` (changelog), and mirror it in `android/.../net/Models.kt` and
   `ContractTest.kt`, all in the same PR. Unknown fields get HTTP 422 (`extra="forbid"`).
9. **The engine only sees what RUKO could really see.** It never reads the simulator's ground
   truth (`is_mule`, `label_*`, journeys, full ledger) at decision time. The payment graph is built
   only from `/v1/decide`, `/v1/episode`, `/v1/payment/received` and bank flows the visibility
   setting allows. Ground truth is for scoring in `data/eval/` only. User baselines (`features/user_baseline.py`,
   `Baselines.get(user, at=ts)`) use only payments before the one being judged; keep it that way.
   `eval/session_eval.py` still hides scam payments from the engine's ledger (an old workaround)
   until it is re-run without it.
10. **Warn, never block, on the phone.** Phone-side alerts (watcher notifications, the Home card)
    only warn. Interruptions at payment time come from the engine. They appear only once there is a
    pattern (episode ACTIVE, or the server answered `high`); a WATCHING episode (one small credit
    from a stranger) is recorded and reported, but not shown.
11. **Humans approve discovered mules.** A graph-discovered suspect affects live scoring only after
    two different analysts approve it (`graph/discover.py`).
12. **Commits and PRs carry only the human author.** No AI co-author or attribution lines.
13. **No LLM in the decision path.** Rules (`rules-0.7`) or the LightGBM scorer (`lgbm-0.2+pg1`) decide tiers. An LLM may only draft
    analyst summaries or playbook descriptions from structured evidence.
14. **Age, gender and language are never model or rule inputs.** They are used only to audit
    outcomes (e.g. false alarms per age band in `eval/session_eval.py`).

## Conventions
- Features are defined once, in `backend/features/build.py` (with its `FAMILY` map). Training,
  replay and evaluation import it; never re-implement a feature. Phone-side episode logic is defined
  once in `contracts/episode_rules.json`; Pay-screen session fields are defined in
  `contracts/README.md` and the simulator (`sim/session.py`) must measure them the same way.
- Every decision writes an evidence record, off the latency path.
- Every user-facing message has English and Hindi strings.
- Add a test with every rule, feature or reason code.
- Python: type hints; Pydantic models mirror `contracts/`.

## Contract (current: c2-0.14)
- `POST /v1/decide`: request `request_id, user_id, payee_upi_id (plain), amount_inr, entry_method,
  payer_says?, ts (+05:30), context {call, device, lures, episode, session, payee_in_contacts, device_verdict}`; response tier T0 to
  T4, reasons, `message_key`, `pause_minutes`, `playbook`, `stage`, `evidence_id`, `fail_open`,
  `threat` (c2-0.8).
- `context.device_verdict` (c2-0.8): the phone's own model verdict (`model_version`, `fraud_class`,
  `level`, family scores `c`/`l`/`b`, `reasons`). The phone runs `device_model.json` on everything
  it measured (its own payment history and every lure hit too) and sends only this conclusion.
  `c`/`l`/`b` are features of the same families (`device_c` C, `device_l` L, `device_b` B, never a
  reason), so the verdict cannot light a family on its own; `fraud_class` names the scam only when
  the server's playbook matcher found none.
- Response `threat` (c2-0.8): `score` 0–100, `level` (`none`/`low`/`medium`/`high`/`critical` for
  T0 to T4), `fraud_type` (the playbook; `null` for T0), `families` (lit families). `null` on fail
  open. See rule 4.
- `context.session` (c2-0.5): how the Pay screen of this payment was used (digit rhythm, paste
  after an app switch, app switches, time away, abandoned tries), counts and rounded seconds only;
  `null` when "Session checks" is off. All its signs are family B, so they can never interrupt on
  their own. `call.speaker_on` (c2-0.5) only adds weight to the C call signal. Field meanings are
  in `contracts/README.md`; phone and simulator must measure them the same way.
- `context.payee_in_contacts` (c2-0.7): yes/no/null, the payee (paid by mobile number, or a
  mobile-style UPI ID) is a saved contact. Never names or numbers. It only softens "new payee" (R6);
  a payee is *known* when the bank's history or a completed payment here (c2-0.6) says so.
- `POST /v1/payment/outcome` (c2-0.6): after the PIN or Cancel, the phone reports `completed` or
  `cancelled` for a payment, in the background. The payment id is the `/v1/decide` `request_id`;
  it is kept in the phone's history, the payment graph (`GET /v1/payments/{id}`) and the console.
- `POST /v1/episode`: the phone's task-scam watcher reports a state change with at most 10
  accounts, only with "Share suspicious accounts" on; reply `episode_risk` in words.
- `POST /v1/feedback` (c2-0.9): what the user did on an alert (slid to pay, waited, called a
  trusted person or 1930, "I know this person" + why, cancelled), only for their own payment, 30 a
  day. "I know this person" is refused (`know_them_not_accepted`) when the payee or caller is listed,
  someone may control the phone, or the payee looks like a mule (payee family lit).
- `POST /v1/watch` (c2-0.9): early warnings before any payment (scam message tag, long unknown call,
  remote access, sideload) move the scam stage; opt-in, tags and counts only.
- `GET /v1/me/payments` (c2-0.9): the user's own payments in words, never a score.
- c2-0.10 (AI-enabled scams): `call.video` (a VoIP call while another app uses the camera: a video
  call, e.g. a deepfake "officer"; strengthens R1, counts for digital arrest; the phone sees only
  that the camera is busy) and `WatchEvent.ai_written` (a scam message that looked AI-written;
  counted for the console). The payment graph's `payee_automated` (bot-scale ring: same amount to or
  from many people at a steady rhythm, `policy.yaml` `automation:`) is payee-family evidence (R11).
- `POST /v1/payment/received` (c2-0.11): a credit the phone's money watch read from a bank SMS (amount,
  sender UPI ID or null, time, and from c2-0.12 `sender_name`, e.g. PNB's `by NAME (vpa) thru UPI`;
  never the text), only with "Share money I receive" on (off by default). Stored in the `received`
  table (sender plain, receiver pseudonymised) for the console (`GET /v1/received`, Transactions →
  Received) and, from c2-0.12, in the payment graph as a sender → user edge (credits of
  `bait_max_inr` or less are bait votes for the crowd signal, payee family). The app's History shows
  received money from the phone's own watcher. A message that reads like a scam is never a credit.
- c2-0.13 (same scam, many phones): `WatchEvent.handles` — money handles from a flagged scam
  message (UPI ID plain; link host and call-back number as salted SHA-256, `watch_rules.json
  handle_salt`, `examples/handle_vectors.json` shared with the phone's `signals/Handles.kt`). The
  server counts distinct users per handle (`graph/campaigns.py`, `policy.yaml campaign:`); a spreading
  payee UPI (`payee_in_campaign`, P) or caller number (`caller_in_campaign`, C) gives reason
  `R13_scam_campaign` — one campaign lights at most one family (rule 5). Console: Overview "Spreading
  now" (`GET /v1/campaigns/spreading`). See `docs/features/campaigns.md`.
- c2-0.14 (scam steps, lure-0.2): `device_verdict.steps_seen` / `steps_unmeasured` in the shared step vocabulary
  `contracts/steps.json` (contact, lure, hook, control, coaching, payment, payee; definitions
  `backend/features/steps.py`, phone port `signals/Steps.kt`, cases `examples/steps_vectors.json`); `LureTag`
  gains `other_scam` and `unclear` (no class reached 0.6; never normal). Plan: `docs/plan-v3.md`.
- Reason codes R1 to R13 (`R10_bait_then_pay`, `R11_ring_link`, `R12_coached_session`,
  `R13_scam_campaign`). `context.money` (c2-0.2) was removed in c2-0.4 and now gets 422; c2-0.1 and
  c2-0.3 to c2-0.13 requests still validate.
- Schemas: `contracts/c2_decide.schema.json`, `contracts/c2_episode.schema.json`,
  `contracts/c2_payment_outcome.schema.json`, `contracts/c2_app_events.schema.json` (c2-0.9). Shared episode
  test cases: `contracts/examples/episode_vectors.json` (run by Python and Kotlin tests).

## Transaction database and explanations
- `backend/store/db.py`: every `/v1/decide` with its full decision (all inputs, `p_scam`, family
  scores, lit families, policy steps, intel status, stage path), outcomes, feedback, watch and
  episode events, cases, trusted payees, reviews. SQLite **in memory** by default (empty on every
  start; each test gets its own); `--db logs/ruko.db` keeps a run; `python -m store.export` writes
  a flat table for training. Users pseudonymised, writes off the payment path.
- Reads (analyst console): `GET /v1/transactions`, `/v1/transactions/{id}`,
  `/v1/users/{hash}/timeline`, `/v1/payments/{id}/explain` (scores, every reason with its inputs and
  strength, every playbook rule checked, policy steps, sources, what the user saw),
  `/v1/metrics/alerts` (alert health), `/v1/store/stats`.
- Console pages (`console/src/pages/`): Overview (alert health card, "Run scenario" demo card),
  Alerts, Cases, Transactions + Payment explanation (linking graph), Suspects (two-analyst review,
  bot-scale tag), Scam rings (members, hubs, victims, money, speed), Emerging patterns (name or
  dismiss), Evaluation (episode, graph, AI-written messages), Explore, AI scammer (scam lab, `--lab`).
- `docs/ml-asks.md`: what each ML model must take in, return and pass.

## Which scorer runs
`api/main.py` scores with the trained model by default (`--scorer ml`): `ml/model/predict.py`
(`lgbm-0.2+pg1`) loads `ml/model/artifacts/v0/server_model.json` (one LightGBM per family on that
family's `build_features` inputs, including the phone's verdict scores `device_c/l/b`; isotonic
calibration; a logistic combiner; reasons taken in turns from the lit families; the rules engine's
playbook matcher). Payee guardrail (`+pg1`): with hard payee evidence (registry listed, an approved
suspect, or a money loop plus a crowd signal) the payee family is at least the rules engine's payee
score, because the simulated worlds' mules are all small and the model reads 35+ payers a week as a shop. If it cannot load (e.g. LightGBM missing) the API logs it and falls back to
`api/rule_scorer.py` (`rules-0.7`); `--scorer rules` forces the rules. `GET /health` and evidence
records report the active scorer's version. `scripts/dev.ps1` / `dev.sh` install LightGBM from
`ml/requirements.txt`, so the demo runs the trained model. `python -m serve` (`ml/serve.py`) still
works and does the same.

Held-out world (`dev_test`) through the real policy: 96.8% of scam payments interrupted (93.7%
without the guardrail) vs 85.3% for `rules-0.7`, 0 vs 6.3 legit interruptions per 1,000 (inflated: the simulated world is too easy,
see `data/eval/realism/FINDINGS.md`). Details in `ml/PLAN.md` §0.

## Run it (Windows)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 -BaitPump   # whole stack + demo data
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 -Stop
```

The script makes `.venv`, generates `data/*.parquet` if missing (`-Regenerate` to rebuild), builds
the console if `console/dist/` is missing (`-BuildConsole` to rebuild; needs Node 18+), starts mock
intel on 8001 and the API with `--demo-clock --lab --seed-demo` (the demo agents fill the console once
at startup), pumps the demo mule and the bait account (`-NoBait` skips it), rebuilds the console when
its source is newer than `console/dist` (so run it after every pull), runs `adb reverse` (8000, and
8001 for the mock NPCI's UPI number mapper) and, on an emulator, seeds Meena's and Rahul's contacts
into the address book (`python -m sim.contacts --data data --user <id> --adb`). If laptop port 8000 is taken, the API moves to the next free port
(8002 on one teammate's laptop) and the phone's 8000 is mapped to it. macOS / Linux: `sh scripts/dev.sh`.

- Analyst console: `http://127.0.0.1:<api port>/console/` (dev server: `cd console && npm run dev`,
  port 5173). `/console/graph` redirects there.
- Python: `PYTHONPATH=backend;ml;data` (PowerShell) or `backend:ml:data`; set
  `PYTHONIOENCODING=utf-8` on Windows (the simulator prints ₹).
- Use `127.0.0.1`, not `localhost`, between services on Windows (IPv6 first adds ~200 ms).

## Tests

```bash
.venv/Scripts/python -m pytest backend/tests -q          # 166 tests (with PYTHONPATH set)
.venv/Scripts/python -m pytest ml/tests -q               # 50 tests (needs: pip install -r ml/requirements.txt)
cd android && JAVA_HOME="/c/Program Files/Android/Android Studio/jbr" sh ./gradlew assembleDebug testDebugUnitTest   # 101 tests
```

Android needs Android Studio's JBR (Java 25): AGP 9.4.1 with built-in Kotlin, Gradle 9.8.1,
compileSdk 37, targetSdk 34, minSdk 26. The system `java` (Java 8) does not work.
`android/local.properties` (not committed) needs `sdk.dir` and optionally `API_BASE_URL`
(or set `ANDROID_HOME` to the SDK folder instead).

Kotlin tests that only need plain Kotlin (`ContractTest`, `SignalsTest`, `DeviceModelTest`,
`DeviceFeaturesTest`, `LureModelTest`) read `contracts/` and `ml/model/artifacts/` from the repo, so
a retrained model or a contract change breaks them instead of the demo.

Functional backend tests that need the payee to be recognised should not depend on machine speed:
use generous time limits like the `engine` fixture in `test_session.py` (intel budget and
`api.main.DEADLINE_S` raised). Keep the real 150 ms / 200 ms limits only in timing tests. With the
real limits, a busy machine turns the demo mule into "unknown payee" and a T3 test sees T1.

Evaluation (slow, minutes): `python -m eval.episode_eval`, `python -m eval.graph_eval`,
`python -m eval.session_eval` write `data/eval/*_results.json` and `data/eval/charts/*.svg`
(results are committed). Latest episode run (history-only baselines), fresh mules, scam rupees
interrupted: 54.2% / 65.3% / 90.5% across its setups. The coached-session result (fresh mules
62.5% → 67.8%, no new false alarms) predates that fix. `data/eval/realism/` compares the simulator
with an older prototype, PaySim and Xente (`FINDINGS.md`): the team data is too easy (e.g. mule
account age alone gives AUC 0.994) and has few scam payments, so read eval numbers with that in
mind. Offline episode features for training:
`python -m features.offline_episode --data data/`.

## Map

**Backend** (`backend/`)
- `api/main.py`: decide path tracker → intel (150 ms, parallel) → features → score → policy →
  evidence; also `/v1/episode`, `/v1/payment/outcome`, `/v1/feedback`, `/v1/watch`,
  `/v1/me/payments`, `/v1/cases`, `/v1/alerts`, `/v1/eval` (episode, graph, `ai_lures`),
  `/v1/graph/*` (incl. `suspects`, `rings`, `rings/{id}`), `/v1/transactions*`,
  `/v1/payments/{id}/explain`, `/v1/users/{hash}/timeline`, `/v1/metrics/alerts`,
  `/v1/patterns/emerging` + `/v1/patterns/{id}/review`, `/v1/demo/run` + `/v1/demo/results`,
  `/v1/lab/*` (only with `--lab`, scam lab),
  `/v1/store/stats`, `/v1/trusted`, `/v1/evidence/*`, `/sim/reset`, and the console mount.
- Scorer: `python -m api.main --scorer ml` (default) runs the trained model `ml/model/predict.py`
  (`lgbm-*`, needs LightGBM from `ml/requirements.txt`; the dev scripts install it) and falls back
  to `api/rule_scorer.py` (`rules-0.7`, hand-set) if it cannot load; `--scorer rules` forces the
  rules. `GET /health` reports which one is running.
- Playbooks (the scam type a payment looks like): `data/playbooks/playbooks.yaml` (data owns the
  list; checked in order, first match wins), read by `api/playbooks.py` (format, loader, the same
  rules built in as the fallback if the file is missing or wrong; `GET /health` says which:
  `file:<version>` or `builtin`). `tests/test_playbooks.py` checks the file and the fallback agree.
  Naming an emerging pattern in the console drafts an entry in this format. A new name needs app
  words for `<tier>_<name>`, else the app shows the tier's generic text. Not the same as the
  simulator's journey scripts in `data/sim_v2/config/playbooks/`.
- `api/policy.py` + `policy.yaml` (incl. the `session:` thresholds; the alert budget never
  applies when the payee family is lit), `api/intel.py` (a slow lookup finishes in the background
  and its answer is reused for 30 min as `cached:<status>`, so a slow source never flips the tier),
  `api/episode_events.py`.
- `features/`: `build.py` (one feature builder; `FAMILY` map), `tracker.py` (stages S0 to S5),
  `episode.py` + `bank_sms.py` (same state machine as the phone), `session.py` (Pay-screen numbers
  → coached-session signs), `user_baseline.py` (history before the payment only),
  `offline_episode.py`.
- `graph/store.py` (crowd signal with thresholds in `policy.yaml` `crowd:`, money loop, bot-scale
  `automation` with `policy.yaml` `automation:`, `new_and_spreading` = an account RUKO first saw
  within 48 h that 3+ users already pay → feature `payee_new_and_spreading` (P, R3; not for verified
  merchants or bank-old accounts), story for the console, one `Payment` per payment id with its
  decision and outcome), `graph/discover.py` (suspects, two-analyst approval, rings, `hub_score`,
  `ring_view`).
- `api/overlay.py` (evidence overlay): RUKO's own cross-user evidence (`policy.yaml`
  `evidence_overlay.features`) counts with any scorer, including the trained model that never
  learned it — it lifts its family and reason, and the policy raises to T2 only when a second
  family is lit (rule 5).
- `store/` (transaction database, export), `api/explain.py`, `api/feedback.py` (feedback, alert
  health), `patterns/emerging.py` (A4, thresholds in `policy.yaml` `emerging:`), `demo/agents.py`
  (scripted victims for every scam type), `demo/lab.py` (scam lab, `--lab`: a judge sends SMS and
  calls to the emulator over adb from the console's "AI scammer" page and sees whether the scam
  worked; four workflows, flagged and quiet), `evalsuite/ai_lures.py` (A3, AI-written scam messages
  test). Each has a page in `docs/features/`.
- `intel_mock/`: NPCI, banks (`payee-risk`, `payee-flows`, visibility none / partner / dpip),
  DoT FRI, I4C registry, with real lags and blind spots.
- `schema/events.py` is the source of truth for the contract; `evidence/store.py` is the
  hash-chained vault.

**Android** (`android/app/src/main/java/com/ruko/demo/`)
- `net/`: models, request builder, Retrofit client. `signals/`: calls, device, lure scorer (`assets/lure.json`), bank
  SMS parser, `DeviceModel.kt` + `DeviceFeatures.kt` + `DeviceVerdict.kt` (on-device model,
  `assets/device_model.json`, c2-0.8; must match `ml/model/artifacts/`), `ContactBook.kt` (payee in contacts, c2-0.7), `SessionTracker.kt` (Pay-screen session, c2-0.5; tested by `SessionTrackerTest`). `shield/`: background task-scam watcher (SMS receiver, workers, episode, notifier,
  encrypted event queue). `data/`: encrypted account store, `PaymentHistory.kt` (payment history: id, decision, outcome; 90 days). `ui/`: screens incl. `HistoryScreen.kt` (bottom-bar History), `ContactsScreen.kt` (To Mobile Number), debug panel (long press
  "Cache Pay" on Home; "Preview alert screens" shows T1 to T4 without the server), `EpisodeCard.kt`.
  `ui/alerts/`: T1 `TipBanner` on the PIN screen, T2 `ExplainCard` (5 s read gate, `SlideToConfirm`),
  T3 `PauseScreen` (countdown, trusted person, 1930, wait reminder, "I know this person"), T4
  `ReviewScreen`; `AlertText.kt` maps `message_key` to words (unknown key → the tier's generic);
  `PaymentViewModel.onAlertAction` is the one place feedback is sent (`POST /v1/feedback`); "I know
  this person" lightens T3 to the T2 card only when the server answers `trusted_accepted`. Alerts use the
  profile language. `ui/MessageCheckScreen.kt` + `signals/MessageCheck.kt` (A5, Home chip "Message
  check"): the last 3 days of SMS labelled on the phone ("matches a scam script" from `lure.json`,
  "looks AI-written" from `assets/ai_text.json` only for personal senders and 12+ words, hidden
  until that model exists, "OTP: never share this"); an OTP during a call gets a full warning, and
  `SmsReceiver` posts it as a notification live ("SMS scam check" + "Call signals" on). A new SMS
  that matches a scam script gets a "may be a scam" notification (scam type, plus "looks
  AI-written" when known; never the text) that opens Message check. Nothing is sent.
  `shield/WatchSender.kt` (Step 7, "Early warnings" switch, off by default): `lure_seen` from SMS and
  from `shield/ChatListener.kt` (chat app notifications, "Check chat messages" switch, off by
  default, needs notification access), `long_unknown_call` when a call ends (`ContextSensor
  .onCallEnded`), `remote_access_on` / `sideload` on app start; rules in `WatchPolicy`, events in an
  encrypted queue sent by WorkManager to `POST /v1/watch`. Hindi strings in `res/values-hi/`.

**ML** (`ml/`, on the path as `model.*`)
- `dataset/` replays the simulated world into point-in-time training rows as the phone and engine
  would have seen them (`phone_view.py` sends the c2-0.8 context, including the phone's
  `device_verdict`, and replays the payment graph).
- `model/train.py`, `predict.py` (`lgbm-0.2+pg1`, payee guardrail), `reasons.py`, `evaluate.py`, `experiments.py`,
  `metrics.py`, `tune.py`; `lure_train.py` + `lure_corpus.py` train the on-phone lure classifier;
  `model/device/` trains, scores and names the verdict of the on-device model.
- Artifacts: `model/artifacts/v0/server_model.json` (server scorer), `v0/device_model.json`
  (+ `device_vectors.json`, `device_feature_vectors.json`, copied to the app's assets),
  `v0/policy_proposal_*.yaml`, `model/artifacts/lure.json` (+ `lure_metrics.json`,
  `lure_vectors.json`); `v1/` is empty.

**Data** (`data/`)
- `sim/generate.py` builds the world (`sim/extras.py` adds hard negatives on a separate random
  stream so the core world and demo identities never shift; `sim/session.py` adds Pay-screen
  sessions the same way). `sim/mule_pump.py`, `sim/bait_pump.py` prepare live demos; `sim/contacts.py` builds a demo user's
  address book (people really paid, plus a few never paid) and seeds it on the emulator.
- `eval/`: `episode_eval.py`, `graph_eval.py`, `session_eval.py` (ground truth used for scoring
  only), `realism/` (`compare.py`, `FINDINGS.md`); `redteam/` is empty. `data/manifest.json` and `data/sample_v0/` are committed;
  `data/*.parquet` is git ignored.

## Demo identities
- User `u_demo_meena` (Cache Pay passcode on the emulator: 482915). Contacts: Sai Das, Aarav Yadav,
  Rahul Kumar, Aarav Mishra (paid before), Arjun Pandey (sends her money), Kiran Sinha, Sunil Yadav,
  Nikhil Singh (never paid).
- Demo mule `secure.settlement.desk@okaxis`; kirana `shreeganesh.kirana@okaxis`.
- Meena scenario (call + remote access + ₹95,000, "government") → T3 `t3_digital_arrest`.
- Bait pump `--check` → T3 `t3_task_job` with R10, R3, R9, R11.
- Coached example (`contracts/examples/decide_request_coached.json`) → T3 or T4 with R12 and R1.

## Not built yet
Pause enforcement and `pause_until` (the app
counts `pause_minutes` from the answer), T4 review polling (no review endpoint), the app's
the "looks AI-written" model (`ai_text.json`, ml/), red-team tests (`data/eval/redteam/` is empty), `docker-compose.yml` / `Makefile`,
Redis / Postgres, signed release APK. SMS permissions are a demo-build feature only (Play Store
does not allow them for a payment app). `ml/PLAN.md` tracks what is done in `ml/` and what it needs
from other folders (its §12).

`.claude/SPEC.md` (local, not in git) is the original long spec. Parts of it are older than the
code (e.g. its endpoint names and repo layout); when they disagree, this file and the code win.
