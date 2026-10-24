# ml: ML and detection

The ML parts of zone 2: features to a calibrated score, reasons and a playbook, the
on-phone lure model and weekly pattern discovery. Branches: `ml/*`.

| Component | Files (inside `ml/`) |
|---|---|
| Scorer (behaviour-only baseline and full RUKO model, LightGBM + isotonic) | `model/train.py`, `model/calibrate.py` |
| Family scores (C, L, P, B) for the corroboration gate | `model/families.py` |
| Reason codes R1 to R8 (SHAP, top three) | `model/reasons.py` |
| Playbook library and matcher | `model/playbooks.py` (data side in `../data/sim/playbooks.yaml`, with data/) |
| Lure classifier (char n-gram TF-IDF + logistic regression) | `model/lure_train.py` → `model/artifacts/lure.json` |
| Pattern discovery (HDBSCAN) | `model/discovery.py` |
| Retraining from feedback | `model/retrain.py` |
| Threshold tuning for `policy.yaml` | `model/tune.py` |
| Interface the API calls: `score(features)` | `model/predict.py` |
| Model card | `model/MODEL_CARD.md` |
| Artifacts handed to the backend | `model/artifacts/v0/` (H18), `model/artifacts/v1/` (H30) |

Also writes `../data/eval/ablation.json` (with data/).

Reads: `../data/train_table.parquet` and the other Parquet files (data/),
`../backend/features/offline.py` and `feature_list.json` (backend/), `../data/lure_texts.csv`.
