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
| Packaging | `../docker-compose.yml`, `../Makefile` (repo root) |

Written by others but served from here:
- `intel_mock/data/*.json` (FRI, Suspect Registry, MuleHunter lists) come from Nikunj.
- `api/policy.yaml` threshold values are proposed by Diwansu at H40.

Reads: `../data/*.parquet` (Nikunj), `../ml/model/predict.py` and `../ml/model/artifacts/` (Diwansu).
Timing logs go to `../logs/decide.jsonl` (git ignored).
