# sim_v2: the RUKO sandbox

A deterministic agent sandbox. Citizens live their lives, look-alikes create honest payments that
look like scams, scam crews run playbooks step by step, victims decide at each step, mules forward
money and get replaced, and reports reach the lists after a lag. The output is the same 7 tables as
`data/sim` (the backend and `ml/` read them unchanged), plus `decisions` and `crews`.

- **Controlled randomness:** every number is drawn inside a range from `config/`, using a stream
  keyed by (seed, who, what).
  - The same seed gives the same world; a new seed gives a new variation.
  - A 500-user world is exactly the first 500 users of the 20,000-user world.
- **Explainable:** every scam payment has a `cause_id` that points to the victim's decision in
  `decisions.parquet`, with the formula's inputs, p, the draw and the outcome.

## Commands (repo root, Git Bash; PowerShell: `$env:PYTHONPATH="backend;ml;data"`)

```bash
export PYTHONPATH="backend;ml;data" PYTHONIOENCODING=utf-8
.venv/Scripts/python -m sim_v2 build                      # 500 users x 14 days -> data/sim_v2_out/small (seconds)
.venv/Scripts/python -m sim_v2 build --users 3000 --days 30 --out data/sim_v2_out/mid
.venv/Scripts/python -m sim_v2 build --users 20000 --days 60 --out data/sim_v2_out/full   # goal size (estimated ~7 min, not run yet)
.venv/Scripts/python -m sim_v2 summary                    # what is in the world
.venv/Scripts/python -m sim_v2 csv                        # data/sim_v2_out/small/csv/*.csv (open in Excel)
.venv/Scripts/python -m sim_v2 show u_000005              # one person's timeline
.venv/Scripts/python -m sim_v2 trace j_demo_0             # one scam as a story (decisions + rows)
.venv/Scripts/python -m sim_v2 playbooks                  # scam state machines
.venv/Scripts/python -m sim_v2 scenarios                  # look-alikes + scripted demo actors
.venv/Scripts/python -m sim_v2 assumptions --guesses      # every guessed number, with source
.venv/Scripts/python -m sim_v2 validate                   # 25 checks: schema vs data/sim, labels, determinism
.venv/Scripts/python -m pytest data/sim_v2/tests -q       # includes the backend engine on sim_v2 data
```

Add `--data DIR` to summary / csv / show / trace / validate to use another world, and
`--seed N` or `--world eval` to build a variation or a realistic-prevalence world.

What every column means, and why some cells are empty: [DATA_DICTIONARY.md](DATA_DICTIONARY.md).
Setup once: `.venv/Scripts/python -m pip install python-docx` (for the Word report).

## Layout

| Path | What |
|---|---|
| `config/world.yaml` | seed, size, dates, train/eval victim rate |
| `config/assumptions.yaml` | every number, with `src` and `conf` (official / data / guess) |
| `config/playbooks/*.yaml` | scam state machines (see `config/playbooks/README.md`) |
| `config/lookalikes.yaml` | honest situations that look like scams (hard negatives) |
| `config/scenarios/demo.yaml` | exact demo actors (Meena, kirana, demo mule) |
| `config/cases.csv` | real case catalogue to fill; used to replace guesses in playbooks |
| `core/` | `rng.py` keyed streams, `config.py` loader, `tables.py` row buffers |
| `world.py` | people, contacts, shops per locality, billers, platforms |
| `rails.py` | the only writers: pay, call, lure, remote app, sideload, decide |
| `agents/citizen.py` | everyday payments, rent, bills, calls, spam, app installs |
| `agents/lookalike.py` | hard negatives |
| `agents/scammer.py` | crews, mule slots and lifetimes, outside victims, forwarding |
| `playbook.py` | runs one journey from a playbook YAML; victim decision formula |
| `agents/lists.py` | victim / outside / bystander / false reports with lags |
| `agents/session.py` | pay-screen sessions (contract c2-0.5) |
| `run.py`, `export.py` | build order and table writing |
| `__main__.py`, `validate.py`, `tests/` | commands and checks |

## Where to look after a build
Every `build` writes, next to the Parquet files in `--out`:
- `report.html` and `report.docx`: **the generation report** (about 30 charts and tables, with a plain-text
  explanation for every section). Re-create it any time with `python -m sim_v2 report --data DIR`;
  the script is `report.py` (add a chart = add a function to `SECTIONS`).
- `summary.txt`: what is in the world (payments by flow, journeys, outcomes, mules, scam share)
- `validate.txt`: the 25 checks with PASS / FAIL
- `csv/*.csv`: every table as CSV (first 1,000 rows + every scam and look-alike row; `csv --all` for everything)

## Changing things
- **A number:** edit `config/assumptions.yaml`, then build again.
- **A new scam:** add `config/playbooks/<name>.yaml`.
- **A new hard negative:** add an entry to `config/lookalikes.yaml`.
- **Several variations:** `--seed 1`, `--seed 2`, ... With `randomise: true` in `world.yaml`, every
  `range` in `assumptions.yaml` is also re-drawn per seed (domain randomisation for training worlds).
