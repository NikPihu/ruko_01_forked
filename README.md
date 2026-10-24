# RUKO (रुको)

A scam workflow shield for UPI. Pause the scam, not the payment.
Amazon AI Cyber Security Hackathon, Track 02. All data is synthetic or public.

## Who owns what

| Folder | Owner | Builds | Branches |
|---|---|---|---|
| [`android/`](android/README.md) | Manjeet Singh | Android app (zone 1) | `android/*` |
| [`backend/`](backend/README.md) | Jagdeep Singh | Risk API, stage tracker, features, policy, evidence, mock intel (zones 2 and 3) | `backend/*` |
| [`ml/`](ml/README.md) | Diwansu Pilania | Scorer, family models, reasons, playbooks, lure model, discovery | `ml/*` |
| [`data/`](data/README.md) | Nikunj Santosh Tangle | Simulator, datasets, evaluation, analyst console (zone 4) | `data/*` |

Merge to `main` by pull request with one review. Keep `main` runnable every hour.

## Layout

```
ruko_01/
├── android/            app: Kotlin + Compose app
├── backend/            backend
│   ├── api/            FastAPI app, routes, intel adapter, policy engine + policy.yaml
│   ├── features/       stage tracker, feature store, payee graph, build_features()
│   ├── intel_mock/     mock FRI / Suspect Registry / MuleHunter on port 8001
│   ├── evidence/       hash chained evidence vault
│   ├── schema/         events.py, the shared contract
│   └── tests/
├── ml/                 ML
│   └── model/          train, calibrate, families, reasons, playbooks, lure, discovery, predict
│       └── artifacts/  v0, v1, lure.json
├── data/               data (generated *.parquet also lands here)
│   ├── sim/            simulator, config, playbooks.yaml, hard negatives, scenarios/
│   ├── eval/           replay, metrics, red team, load test, results.json, charts/
│   ├── console/        draft report (the analyst console itself is ../console/)
│   ├── sample_v0/      small sample dataset
│   └── external/       public datasets (not committed)
├── console/            analyst console (React + TypeScript), served by the API at /console/
├── docker-compose.yml  (backend, to add)
└── Makefile            (backend, to add)
```

## Paths in the guides vs this repo

The build guides use paths from the repo root. In this repo each person's code sits
inside their folder, so add the folder in front:

| Guide says | In this repo |
|---|---|
| `api/`, `features/`, `intel_mock/`, `evidence/`, `schema/`, `tests/` | `backend/...` |
| `model/` | `ml/model/` |
| `sim/`, `eval/`, `console/` | `data/sim/`, `data/eval/`, `data/console/` |
| `data/*.parquet`, `data/lure_texts.csv` | unchanged |

Python imports do not change. Put the three Python folders on the path and
`from model.predict import score`, `from features.build import build_features` and
`from sim import ...` work exactly as in the guides:

```bash
export PYTHONPATH=backend:ml:data
```

## Run the whole demo (backend + phone)

One script sets up `.venv`, generates `data/*.parquet` if it is missing, starts the mock
intel (8001) and the risk API (8000, `--demo-clock`), pumps the demo mule and runs
`adb reverse` so the Cache Pay app on a USB phone or emulator reaches the API.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1          # Windows
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 -Stop
```

```bash
sh scripts/dev.sh            # macOS / Linux
sh scripts/dev.sh stop
```

If port 8000 is already taken on the laptop, the API moves to the next free port and
`adb reverse` maps the phone's 8000 to it, so the app needs no change. Logs go to `logs/`.
Then install the app (`android/`, `gradlew installDebug`) and tap "Check Scam Shield".

Generated files: `data/manifest.json` and the small `data/sample_v0/` world are committed;
the full `data/*.parquet` is not (rebuild with `-Regenerate` / `REGENERATE=1`).

## Fixed values (team contract)

Ports: API 8000 (also serves the analyst console at /console/), mock intel 8001,
console dev server 5173, Redis 6379, Postgres 5432.
Phone to API: `adb reverse tcp:8000 tcp:8000`, phone calls `http://localhost:8000`.
Secrets such as `PAYEE_SALT` go in `.env` (copy `.env.example`) and never get committed.
