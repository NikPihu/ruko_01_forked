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
| `ml/` | Diwansu Pilania | Scorer, families, reasons, playbooks, lure model (not started: only empty `artifacts/`) |
| `data/` | Nikunj Santosh Tangle | Simulator (`sim/`), evaluation (`eval/`), generated datasets |
| `contracts/` | shared | Published contract, generated from `backend/schema/events.py` |
| `docs/` | shared | Design briefs, e.g. `task-scam-watcher.md` (built; build notes in its §12) |

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
4. **Never show the score.** `p_scam` stays on the server. Users and analysts see tiers, bands and
   reasons in words (English and Hindi).
5. **Two independent families before interrupting.** Families are C context, L lure, P payee,
   B behaviour. T2 or higher needs at least two lit families (`api/policy.yaml`
   `corroboration_min_families`). One source of evidence must never light two families: the whole
   phone episode (`context.episode`) is one L signal, and graph / crowd signals are P only.
6. **Thresholds live in config, not code.** Policy numbers in `backend/api/policy.yaml`; episode
   numbers in `contracts/episode_rules.json` (the phone copies it to
   `android/app/src/main/assets/`, and `EpisodeTrackerTest` checks the copy).
7. **Privacy by default.** Phone data is AES-256-GCM encrypted with an Android Keystore key in
   `noBackupFilesDir`, excluded from backup; "Delete my data" removes the files and the key. RUKO
   users are pseudonymised on the server (`evidence/store.py` `pseudonym()`); payees, bait senders
   and cash-out accounts stay plain because they must be looked up. New consents default to off.
8. **A contract change is one change everywhere.** Edit `backend/schema/events.py`, bump
   `CONTRACT_VERSION`, run `python -m schema.export`, update `contracts/examples/` and
   `contracts/README.md` (changelog), and mirror it in `android/.../net/Models.kt` and
   `ContractTest.kt`, all in the same PR. Unknown fields get HTTP 422 (`extra="forbid"`).
9. **The engine only sees what RUKO could really see.** It never reads the simulator's ground
   truth (`is_mule`, `label_*`, journeys, full ledger) at decision time. The payment graph is built
   only from `/v1/decide`, `/v1/episode` and bank flows the visibility setting allows. Ground truth
   is for scoring in `data/eval/` only. Known leak, not fixed: `features/user_baseline.py` builds
   baselines from the whole ledger; evaluations exclude scam payments from it.
10. **Warn, never block, on the phone.** Phone-side alerts (watcher notifications, the Home card)
    only warn. Interruptions at payment time come from the engine.
11. **Humans approve discovered mules.** A graph-discovered suspect affects live scoring only after
    two different analysts approve it (`graph/discover.py`).
12. **Commits and PRs carry only the human author.** No AI co-author or attribution lines.

## Contract (current: c2-0.4)
- `POST /v1/decide`: request `request_id, user_id, payee_upi_id (plain), amount_inr, entry_method,
  payer_says?, ts (+05:30), context {call, device, lures, episode}`; response tier T0 to T4,
  reasons, `message_key`, `pause_minutes`, `playbook`, `stage`, `evidence_id`, `fail_open`.
- `POST /v1/episode`: the phone's task-scam watcher reports a state change with at most 10
  accounts, only with "Share suspicious accounts" on; reply `episode_risk` in words.
- Reason codes R1 to R11 (`R10_bait_then_pay`, `R11_ring_link`). `context.money` (c2-0.2) was
  removed and now gets 422.
- Schemas: `contracts/c2_decide.schema.json`, `contracts/c2_episode.schema.json`. Shared episode
  test cases: `contracts/examples/episode_vectors.json` (run by Python and Kotlin tests).

## Run it (Windows)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 -BaitPump   # whole stack + demo data
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 -Stop
```

The script makes `.venv`, generates `data/*.parquet` if missing (`-Regenerate` to rebuild), builds
the console if `console/dist/` is missing (`-BuildConsole` to rebuild; needs Node 18+), starts mock
intel on 8001 and the API with `--demo-clock`, pumps the demo mule (and with `-BaitPump` the bait
account), and runs `adb reverse`. If laptop port 8000 is taken, the API moves to the next free port
(8002 on Manjeet's laptop) and the phone's 8000 is mapped to it. macOS / Linux: `sh scripts/dev.sh`.

- Analyst console: `http://127.0.0.1:<api port>/console/` (dev server: `cd console && npm run dev`,
  port 5173). `/console/graph` redirects there.
- Python: `PYTHONPATH=backend;ml;data` (PowerShell) or `backend:ml:data`; set
  `PYTHONIOENCODING=utf-8` on Windows (the simulator prints ₹).
- Use `127.0.0.1`, not `localhost`, between services on Windows (IPv6 first adds ~200 ms).

## Tests

```bash
.venv/Scripts/python -m pytest backend/tests -q          # 107 tests (with PYTHONPATH set)
cd android && JAVA_HOME="/c/Program Files/Android/Android Studio/jbr" sh ./gradlew assembleDebug testDebugUnitTest   # 43 tests
```

Android needs Android Studio's JBR (Java 25): AGP 9.4.1 with built-in Kotlin, Gradle 9.8.1,
compileSdk 37, targetSdk 34, minSdk 26. The system `java` (Java 8) does not work.
`android/local.properties` (not committed) needs `sdk.dir` and optionally `API_BASE_URL`.

Evaluation (slow, minutes): `python -m eval.episode_eval`, `python -m eval.graph_eval` write
`data/eval/*_results.json` and `data/eval/charts/*.svg`. Offline episode features for training:
`python -m features.offline_episode --data data/`.

## Map

**Backend** (`backend/`)
- `api/main.py`: decide path tracker → intel (150 ms, parallel) → features → score → policy →
  evidence; also `/v1/episode`, `/v1/cases`, `/v1/alerts`, `/v1/eval`, `/v1/graph/*`,
  `/v1/trusted`, `/v1/evidence/*`, `/sim/reset`, and the console mount.
- `api/rule_scorer.py` (`rules-0.3`, hand-set fallback until `ml/model/predict.py` exists),
  `api/policy.py` + `policy.yaml`, `api/intel.py`, `api/episode_events.py`.
- `features/`: `build.py` (one feature builder; `FAMILY` map), `tracker.py` (stages S0 to S5),
  `episode.py` + `bank_sms.py` (same state machine as the phone), `offline_episode.py`.
- `graph/store.py` (crowd signal, money loop, story for the console), `graph/discover.py`.
- `intel_mock/`: NPCI, banks (`payee-risk`, `payee-flows`, visibility none / partner / dpip),
  DoT FRI, I4C registry, with real lags and blind spots.
- `schema/events.py` is the source of truth for the contract; `evidence/store.py` is the
  hash-chained vault.

**Android** (`android/app/src/main/java/com/ruko/demo/`)
- `net/`: models, request builder, Retrofit client. `signals/`: calls, device, lure scorer, bank
  SMS parser. `shield/`: background task-scam watcher (SMS receiver, workers, episode, notifier,
  encrypted event queue). `data/`: encrypted account store. `ui/`: screens, debug panel (long press
  "Cache Pay" on Home), `EpisodeCard.kt`. Hindi strings in `res/values-hi/`.

**Data** (`data/`)
- `sim/generate.py` builds the world (`sim/extras.py` adds hard negatives on a separate random
  stream so the core world and demo identities never shift). `sim/mule_pump.py`,
  `sim/bait_pump.py` prepare live demos. `data/manifest.json` and `data/sample_v0/` are committed;
  `data/*.parquet` is git ignored.

## Demo identities
- User `u_demo_meena` (Cache Pay passcode on the emulator: 482915).
- Demo mule `secure.settlement.desk@okaxis`; kirana `shreeganesh.kirana@okaxis`.
- Meena scenario (call + remote access + ₹95,000, "government") → T3 `t3_digital_arrest`.
- Bait pump `--check` → T3 `t3_task_job` with R10, R3, R9, R11.

## Not built yet
Real T1 to T4 alert screens (the decision screen is a placeholder), feedback endpoint and buttons,
the trained ML model and `lure.json`, `docker-compose.yml` / `Makefile`, Redis / Postgres, signed
release APK. SMS permissions are a demo-build feature only (Play Store does not allow them for a
payment app).
