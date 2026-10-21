# backend: Jagdeep Singh (backend, risk engine, integrator)

Zone 2 (non-ML parts of the PSP / bank cloud) and zone 3 (external intel, mocked).
If `main` runs, the team can demo. Branches: `backend/*`.

| Component | Files (inside `backend/`) |
|---|---|
| API gateway | `api/main.py`, `api/routes/` |
| Workflow stage tracker | `features/tracker.py` |
| Feature store | `features/store.py`, `features/user_baseline.py` |
| Payee intel graph | `features/payee_graph.py` |
| Feature builder (one `build_features()` online and offline) | `features/build.py`, `features/offline.py` |
| Feature list (frozen at P1 with Diwansu) | `features/feature_list.json` |
| Intel adapter + mock intel on port 8001 | `api/intel.py`, `intel_mock/app.py` |
| Policy engine (tiers, gate, budget) | `api/policy.py`, `api/policy.yaml` |
| Evidence vault (SHA-256 hash chain) | `evidence/store.py` |
| Cases, feedback, demo controls | `api/routes/cases.py`, `api/routes/feedback.py`, `api/routes/sim.py` |
| Shared schema (everyone mirrors it) | `schema/events.py` |
| Schema test | `tests/test_schema.py` |
| Published contract (JSON Schema + examples) | `schema/export.py` → `../contracts/` |
| Packaging | `../docker-compose.yml`, `../Makefile` (repo root) |

Written by others but served from here:
- `intel_mock/data/*.json` (FRI, Suspect Registry, MuleHunter lists) come from Nikunj.
- `api/policy.yaml` threshold values are proposed by Diwansu at H40.

Reads: `../data/*.parquet` (Nikunj), `../ml/model/predict.py` and `../ml/model/artifacts/` (Diwansu).
Timing logs go to `../logs/decide.jsonl` (git ignored).

## Run it (current MVP)

```bash
pip install -r backend/requirements.txt
export PYTHONPATH=backend:ml:data          # Windows PowerShell: $env:PYTHONPATH="backend;ml;data"

python -m sim.generate --users 2000 --days 30 --out data/     # synthetic world -> data/*.parquet
python -m intel_mock.app --data data --port 8001              # mock NPCI, banks, DoT FRI, I4C registry
python -m api.main --data data --port 8000                    # RUKO risk engine (POST /v1/decide)
python -m sim.mule_pump --payers 40                           # pump the demo mule before the demo
pytest backend/tests
```

Use `127.0.0.1`, not `localhost`, between services on Windows: `localhost` tries IPv6 first and
adds ~200 ms per new connection, which alone breaks the 150 ms intel budget.

What is here so far:
- `api/main.py` decide path: tracker -> intel (150 ms, parallel) -> build_features -> score -> policy -> evidence; 200 ms deadline, fails open.
- `api/rule_scorer.py` rule-based fallback with the same `score()` output shape as `ml/model/predict.py`.
- `intel_mock/` one mock per real organisation, reproducing their blind spots (lag, coverage, false entries).
- `docs/` notes on how the real systems work and how the mocks copy them.

## Run against the phone

1. Regenerate the data if `data/*.parquet` is missing (it is gitignored), start both services as
   above, and add `--demo-clock` to the engine:
   `python -m api.main --data data --port 8000 --demo-clock`.
   The phone sends today's time, but the synthetic world lives at the sim clock (data end,
   2026-11-07). With the flag, the engine decides at the sim clock instead. `GET /health` shows
   `"demo_clock": true`.
2. Pump the mule: `python -m sim.mule_pump --payers 40`.
3. With the phone on USB, run `adb reverse tcp:8000 tcp:8000`. The app's default
   `http://localhost:8000/` then reaches the laptop, and cleartext to localhost is already allowed.
   Over Wi-Fi instead, the app needs the laptop's LAN IP in `network_security_config.xml`, and
   Windows Firewall must allow inbound TCP 8000.
4. Check: tap "Check Scam Shield" in the app. It should show `status ok`.

The request/response shape the app must send is published in `../contracts/` (see its README).
`schema/events.py` stays the source of truth. After changing it, run `python -m schema.export`.

The Android app sends contract `c2-0.1` (since PR #6). `../scripts/dev.ps1` / `dev.sh` start
this stack and connect the phone in one step.

## Task-scam watcher and payment graph (contracts c2-0.3, c2-0.4)

Brief: `../docs/task-scam-watcher.md` (build notes at its end).

| Piece | Files |
|---|---|
| Episode state machine (same as the phone's) and the SMS parser it is tested with | `features/episode.py`, `features/bank_sms.py` |
| Episodes rebuilt from the ledger for training | `features/offline_episode.py` -> `../data/episode_features.parquet` |
| `POST /v1/episode`, account lookups, episode risk, analyst cases (`GET /v1/cases`) | `api/episode_events.py` |
| Payment graph: crowd signal, money loop, mock bank flows | `graph/store.py`, `intel_mock/bank.py` (`/banks/{code}/payee-flows/{upi}`) |
| Mule discovery (hourly), two-person review, console API | `graph/discover.py`, `GET /v1/graph/account/{upi}`, `GET /v1/graph/story/{upi}`, `GET /v1/graph/suspects`, `POST /v1/graph/suspects/{upi}/review` |
| Analyst console reads | `GET /v1/alerts` (payments at T1+), `GET /v1/cases`, `GET /v1/eval`; the built console (`../console/`) is served at `/console/` |
| Payment ids and outcomes (c2-0.6): one record per `/v1/decide` request_id, completed / cancelled from the phone | `graph/store.py` (`Payment`, `record_outcome`), `POST /v1/payment/outcome`, `GET /v1/payments/{id}`, `GET /v1/graph/payments/{upi}` |

```bash
python -m features.offline_episode --data data/
python -m sim.bait_pump --api http://127.0.0.1:8000 --check   # after sim.mule_pump; then open /console/
python -m eval.episode_eval                                      # task-scam rupees stopped, 3 setups
python -m eval.graph_eval                                        # mules flagged before registry listing
```

Known gap: `features/user_baseline.py` builds each user's baseline (largest payment, known payees)
from the whole ledger, including the payment being judged. The evaluations work around it.

Not done yet: feedback, report, prefetch and pause enforcement endpoints;
Redis/Postgres; docker-compose.
