# data: data, evaluation and console

The world RUKO is tested in, the proof that it works, and the analyst console (zone 4).
Branches: `data/*`.

| Component | Files (inside `data/`) |
|---|---|
| Journey simulator | `sim/generate.py`, `sim/config.yaml` |
| Playbook library (data side, with ml/) | `sim/playbooks.yaml` |
| Hard negatives | `sim/hard_negatives.yaml` |
| Demo scenarios | `sim/scenarios/meena.json`, `kirana.json`, `adaptive.json` |
| Mock intel lists (served by the backend) | `../backend/intel_mock/data/*.json` |
| Fraud ops analyst console (Streamlit, port 8501) | `console/app.py` |
| Draft 1930 / CFCFRMS report ("draft, not filed") | `console/report.py` |
| Replay, metrics, ablation, fairness | `eval/replay.py`, `eval/metrics.ipynb` |
| Load test and red team journeys | `eval/locustfile.py`, `eval/redteam/*.json` |
| Comprehension test | `eval/comprehension.csv` |
| Final numbers for the slides | `eval/results.json`, `eval/charts/` |

Generated datasets also live in this folder, at the paths the guides use:
- `data/*.parquet` (users, payees, transactions, journeys, train table, stage labels): git ignored, too big
- `data/manifest.json`, `data/lure_texts.csv`: committed
- `data/sample_v0/`: small sample, committed so everyone can start before H10
- `data/external/`: public datasets such as the UCI SMS Spam Collection (git ignored)

Top priority: full Parquet data to backend and ML by H10.
