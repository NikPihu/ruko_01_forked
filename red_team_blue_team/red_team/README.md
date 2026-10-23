# Red team

**Nikunj's 50 breakthrough playbooks** (`playbooks/`, his notes in `NIKUNJ_README.md`, his own scores
in `nikunj_manifest_and_scores.csv`): sim_v2 scam scripts written to slip past RUKO. They are data
(YAML in the `data/sim_v2/config/playbooks/` format), never executed: the simulator plays them out
against simulated users, and RUKO judges every payment as it would live.

The tricks they use, as the blue team reads them from each script (`blue_team/redteam.py`):

| Trick | Playbooks | Why it hurts RUKO |
|---|---|---|
| QR / contact only | 50 | no typed payee: no R6, no "who are you paying?" |
| diluted mules (8+ slots, merchant-disguised / rented) | 50 | payee fan-in and MuleHunter signals stay low |
| notification-only hook (WhatsApp, Telegram, Instagram) | 25 | the phone cannot read it: lure family L stays dark |
| pays 30+ minutes after the call ends | 15 | no live call at Pay: context family C stays dark |
| SMS hook scored below 0.6 | 10 | below the lure model's send threshold |
| tiny anchor payment first | 8 | later payments go to a "known payee" |
| one bait credit | 5 | the task-scam watcher never turns ACTIVE |

## Use them

From the blue-team console (`python -m blue_team app`, page **Red team**): *Build the red-team world*
(a sim_v2 world with RUKO's six known scams plus these 50; sim_v2's own unknown scams are left out),
then start a run on it, then open **Scorecard**. Or on the command line:

```bash
python -m blue_team.testworld --red-team --users 4000 --days 30 --victim-rate 0.8 --seed 41 --out data/sim_v2_out/redteam
python -m dataset.replay --data data/sim_v2_out/redteam --out ml/data/tables/redteam.parquet --warmup-days 7
python -m blue_team run --table ml/data/tables/redteam.parquet --data data/sim_v2_out/redteam
```

The scorecard measures, per playbook, the share of its scam payments RUKO interrupted (next to
Nikunj's claim), where its complaints went, and whether the blue team drafted a playbook for a group
it dominates. It is the only place that uses the simulator's answer key.

Adding a playbook: drop a new sim_v2 YAML here (unique `name`, `emerging: true`); the console picks
it up. The `python -m redteam` runner Nikunj's notes mention is not in this folder.
