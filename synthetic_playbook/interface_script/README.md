# interface_script: run a playbook against the RUKO server

Takes a scam playbook, builds a world where it is the only scam running, sends every record to the
server the way a phone would, and reports whether the server caught it.

No LLM anywhere. The scam steps come from the playbook file; the records come from `data/sim_v2`;
the answers come from the real engine.

## The question it answers
For each payment the server replies with a **threat score, 0–100**.

- A payment the server scores at or below **70** (`normal_max_score`) is the server **calling it normal**.
- If **75%** (`breakthrough_share`) of a playbook's scam payments come back normal, that playbook
  **got through**: one miss is noise, most missed is a finding.
- A breakthrough is written to `handoff/` for the blue team.

Both numbers are in `config/runner.yaml` and can be changed per run
(`--normal-max-score`, `--breakthrough-share`).

## Setup (once, from the repo root)
```powershell
$env:PYTHONPATH = "backend;ml;data;synthetic_playbook"; $env:PYTHONIOENCODING = "utf-8"
```
Git Bash: `export PYTHONPATH="backend;ml;data;synthetic_playbook" PYTHONIOENCODING=utf-8`

## Commands
```bash
.venv/Scripts/python -m interface_script playbooks                      # what can be run
.venv/Scripts/python -m interface_script run --playbook task_job        # one playbook
.venv/Scripts/python -m interface_script run --playbook path/to/mine.yaml --victims 30
.venv/Scripts/python -m interface_script run-all                        # all 12, with a table
.venv/Scripts/python -m interface_script show  <run-dir>                # a finished run
.venv/Scripts/python -m interface_script trace <run-dir> --journey j_000123
```

`--playbook` takes a name from `data/sim_v2/config/playbooks/` or a path to any YAML in that format
(see `data/sim_v2/config/playbooks/README.md`).

### Adding playbooks
There is no list to update. **Drop a YAML into a folder and point `run-all` at the folder:**
```bash
.venv/Scripts/python -m interface_script run-all --playbooks path/to/my_playbooks
```
Every `*.yaml` / `*.yml` in it is run (in name order), each into its own result folder, and
`all_playbooks.csv` compares them. Without `--playbooks` it runs sim_v2's library.

### Which server
- `--server local` (default): the real engine runs inside the script. Nothing to start.
- `--server http://127.0.0.1:8000`: a server you started yourself. It must be running on the world
  this script built, so start it with `--data <run-dir>/world` after the build, or use `local`.
- `--scorer ml` (default) or `--scorer rules` picks the scorer for the local engine. The run prints
  which one answered, and it is saved in `verdict.json`.

## What a run writes (`synthetic_playbook/interface_script_out/<playbook>/`)
| File | What it holds |
|---|---|
| `summary.txt` | the verdict in words: judged, missed, detected, false alarms |
| `verdict.json` | the same as numbers, incl. `breakthrough` true/false |
| `results.csv` | one row per payment: amount, threat score, tier, reasons, `called_normal` |
| `requests.jsonl` / `responses.jsonl` | exactly what was sent and what came back |
| `playbook.yaml` | the scenario that was run |
| `world/` | the generated world (sim_v2 tables) |
| `handoff/` | only on a breakthrough: the playbook, the missed payments, the verdict |

## How the parts fit (and where the blue team plugs in)
```
scenario.py  playbook -> a world where it is the only scam   (copies sim_v2 config to a temp dir)
records.py   world -> the records a phone would send         (reuses ml/dataset/replay phone view)
server.py    local engine or a URL                           (same two methods either way)
judge.py     threat score -> normal or not -> breakthrough
sinks.py     where a finished run goes
```

**The blue team is a sink.** Add a function to `SINKS` in `sinks.py` and it receives every run
(verdict, scenario, results, output folder). Nothing else changes.

## Notes
- The first `warmup_days` (default 7) build each user's history; answers about those payments are
  not judged, because the server has nothing to compare against yet.
- `victims_mode: comply` (default) makes victims pay at every step, so every step is put to the
  server. `model` uses sim_v2's own decide/refuse formula instead: fewer payments, more realistic.
- Honest payments are sent too (`normal_sample`, default 0.25) and reported as false alarms, so a
  playbook cannot look good just because the server was lenient with everything.
- **Fail-open** replies (rule 3: the check did not finish in 200 ms, so the server answered T0 with
  no score) are counted on their own and left out of the miss rate: the playbook was never judged.
