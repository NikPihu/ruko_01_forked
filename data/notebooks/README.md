# data/notebooks: synthetic data analysis

00–02 cover sim_v1 (the first attempt); 03 covers sim_v2, the sandbox (`data/sim_v2/README.md` lists its commands). Each section asks one question, shows one table or chart, and ends with **Inference**.

| Notebook | Question | Needs | Time |
|---|---|---|---|
| `00_reference_datasets.ipynb` | Can any downloaded dataset be used? | `data/eval/datasets/scorecard.json` (or the raw files in `data/external/reference_datasets/` with `RERUN = True`) | seconds (≈1.5 min with rerun) |
| `01_build_sim_v1.ipynb` | Calibrate to NPCI, build the train and eval worlds, look inside | nothing | ≈1.5 min |
| `02_v1_real_vs_synthetic.ipynb` | Is sim_v1 close to real data, and better than `data/sim`? | notebook 01 first; Xente parquet in `reference_datasets/real_world/xente/` | ≈2 min |
| `03_sandbox_walkthrough.ipynb` | **sim_v2:** build a world, trace one scam, why victims paid, why scams are hard to spot, mules, seeds | nothing (builds 3,000 users x 30 days) | ≈1 min |

## Setup (once, Windows, from the repo root)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r backend\requirements.txt numpy scikit-learn lightgbm matplotlib optuna openpyxl jupyterlab
```

## Open the notebooks

```powershell
.venv\Scripts\jupyter-lab data\notebooks
```

Or open the `.ipynb` in VS Code and pick the `.venv` interpreter as the kernel. Run with **Run All**.

## Same steps without notebooks

```powershell
$env:PYTHONPATH = "backend;ml;data"; $env:PYTHONIOENCODING = "utf-8"
.venv\Scripts\python -m eval.datasets.score                      # scorecard -> data/eval/datasets/scorecard.json
.venv\Scripts\python -m sim_v1.calibrate --trials 200            # -> data/sim_v1/calibrated.json
.venv\Scripts\python -m sim_v1.generate --world train --out data/sim_v1_out/train
.venv\Scripts\python -m sim_v1.generate --world eval --users 10000 --seed 11 --out data/sim_v1_out/eval
```

Outputs go to `data/sim_v1_out/` (git ignored). To try a change, edit a value in `data/sim_v1/config.py`
(e.g. `activity_sigma`, `mule_kinds`, `victim_rate_train`) and re-run notebooks 01 and 02.
