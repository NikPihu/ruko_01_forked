# Playbooks: how a scam runs, step by step

One YAML file = one scam type. `python -m sim_v2 playbooks` lists them. A new file here is picked
up automatically; no code change is needed.

## How a journey runs
1. A crew targets a user (more likely for the personas in `targets`). The journey starts at a time
   inside `start_hours`.
2. Steps run in order. Before each step the clock moves on by `gap_min` (minutes, a range).
3. A step can:
   - emit **events** the phone could see: `call`, `sms_lure`, `notification_lure`, `remote_app`, `sideload_apk`;
   - make the **crew pay** the victim (`crew_pays`: bait credits, fake profits);
   - **ask** the victim to pay (`ask`).
4. At every `ask`, and at steps with `decide`, **the victim decides**: comply, delay or refuse.
   - The formula is in `assumptions.yaml` → `victim`, and every term is logged in `decisions.parquet`.
   - Refusing ends the journey; then the victim may report it.
5. `ask` options: `amount`, `split` (tranches), `repeat`, `entry`, `round` (share rounded to ₹100),
   `pressure`, `mule`, and `during_call: true` (a coached payment made while the scam call is still on).
6. Payments go to the crew's current mules (`mule: same | rotate | second`). Mules forward the money
   on their own (see `agents/scammer.py`: hold, pass-through, cash-out).

## Range syntax (used everywhere)
| Spec | Meaning |
|---|---|
| `5` | fixed |
| `[lo, hi]` | uniform |
| `{log: [lo, hi]}` | log-uniform (money, durations) |
| `{int: [lo, hi]}` | whole number, inclusive |
| `{of: prev, x: [a, b]}` | previous ask × factor (escalation) |
| `{of: total, x: [a, b]}` | everything paid so far × factor ("tax to withdraw") |

## How to make a playbook more real
- Every playbook has `confidence` (guess | public_case | official) and `sources`.
- Add real cases to `../cases.csv`: one row per reported case, from news, police or I4C advisories,
  with the number of payments, amounts, gaps, channel and a source URL.
- When a playbook has 10 or more cases, set its ranges from them (e.g. the 10th–90th percentile of
  the first payment), then change `confidence` to `public_case` and list the sources.
- Red-team moves (ml/PLAN.md, deck A3) are variants: copy a playbook, change one thing (e.g.
  `split` tranches, `end_call_before_pay: true`), and give it a new name.
