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

The red team is run by **Nikunj's runner**, `synthetic_playbook/interface_script` (team main, PR #27):
each playbook plays out in its own small sim_v2 world against the **real RUKO engine**, and every
reply is judged by its threat score (70 or less = RUKO called it normal). When 75% of a playbook's
scam payments come back normal it is a **breakthrough**, and the runner's `blue_team` sink
(`interface_script/sinks.py`) drops it into the blue team's inbox (`blue_team/inbox.py`).

From the blue-team console (`python -m blue_team app`, page **Red team**):
1. **Run the red team** over these 50 (or sim_v2's own library): several at a time, resumable.
2. **The blue-team inbox** fills with every verdict and each breakthrough.
3. **Build the attack world** from the breakthroughs (one world where they all run at once, next to
   RUKO's six known scams), replay it, then start a blue-team run on it and open **Scorecard**.

Command line, the same steps:

```bash
export PYTHONPATH="backend;ml;data;synthetic_playbook;red_team_blue_team" PYTHONIOENCODING=utf-8
python -m interface_script run-all --playbooks red_team_blue_team/red_team/playbooks
python -m blue_team.testworld --red-team --red-dir red_team_blue_team/blue_team/inbox/breakthroughs --users 4000 --days 30 --victim-rate 0.8 --seed 41 --out data/sim_v2_out/redteam
python -m dataset.replay --data data/sim_v2_out/redteam --out ml/data/tables/redteam.parquet --warmup-days 7
python -m blue_team run --table ml/data/tables/redteam.parquet --data data/sim_v2_out/redteam
```

The scorecard puts, per playbook, the runner's verdict (alone in its own world) next to what RUKO
did in the shared attack world, where its complaints went, and whether the blue team drafted a
playbook for a group it dominates. It is the only place that uses the simulator's answer key.

Adding a playbook: drop a new sim_v2 YAML here (unique `name`, `emerging: true`); the console picks
it up.

## First result (offline agents, 4,000 users x 30 days, seed 41)

1,609 scam journeys, 1,436 by these 50 playbooks (all 50 attacked), 845 red-team scam payments.
**RUKO (lgbm-0.2 + policy) interrupted 2.8% of them**, which bears out Nikunj's claim (97.5% missed),
while it still interrupted digital_arrest 100%, fake_kyc_apk 100%, refund_qr 89% and
fake_customer_care 85% of their payments. Then the blue team: 304 complaints (275 missed), 24 HDBSCAN
groups; all 50 red-team playbooks produced complaints, 49 landed in a group, 19 are the majority of
a group that got a drafted playbook, 14 of those judged a new scam (offline analyst; run with Bedrock
for the LLM agents).
