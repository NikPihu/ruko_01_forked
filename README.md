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
├── android/            Manjeet: Kotlin + Compose app
├── backend/            Jagdeep
│   ├── api/            FastAPI app, routes, intel adapter, policy engine + policy.yaml
│   ├── features/       stage tracker, feature store, payee graph, build_features()
│   ├── intel_mock/     mock FRI / Suspect Registry / MuleHunter on port 8001
│   ├── evidence/       hash chained evidence vault
│   ├── schema/         events.py, the shared contract
│   └── tests/
├── ml/                 Diwansu
│   └── model/          train, calibrate, families, reasons, playbooks, lure, discovery, predict
│       └── artifacts/  v0, v1, lure.json
├── data/               Nikunj (generated *.parquet also lands here)
│   ├── sim/            simulator, config, playbooks.yaml, hard negatives, scenarios/
│   ├── eval/           replay, metrics, red team, load test, results.json, charts/
│   ├── console/        Streamlit analyst console + draft report
│   ├── sample_v0/      small sample dataset
│   └── external/       public datasets (not committed)
├── docker-compose.yml  (Jagdeep, to add)
└── Makefile            (Jagdeep, to add)
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

## Fixed values (team contract)

Ports: API 8000, mock intel 8001, console 8501, Redis 6379, Postgres 5432.
Phone to API: `adb reverse tcp:8000 tcp:8000`, phone calls `http://localhost:8000`.
Secrets such as `PAYEE_SALT` go in `.env` (copy `.env.example`) and never get committed.
