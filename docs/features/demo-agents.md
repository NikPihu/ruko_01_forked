# Demo agents: every scam type, live

**What it does.** Scripted people use the real RUKO API, so a demo or a test run shows every scam
type end to end, and the console fills up.

**Run it.**
- **Whole stack:** `scripts\dev.ps1 -BaitPump` starts the stack. Then run:
  `PYTHONPATH=backend;ml;data python -m demo.agents --api http://127.0.0.1:8000 --intel http://127.0.0.1:8001 --all`
- **Or from the console:** **Overview → Run scenario** (`POST /v1/demo/run`; results at
  `GET /v1/demo/results`).

**Scenarios** (`backend/demo/agents.py`):

| Scenario | The person | Expected |
|---|---|---|
| `digital_arrest` | unknown call + screen sharing + a big payment to the demo mule | pause (T3+), digital arrest |
| `deepfake_video` | video call from an unknown caller while paying | interrupted (T2+), digital arrest |
| `fake_kyc` | KYC message + an app from outside the store | interrupted (T2+), fake KYC app |
| `trading_group` | trading-tip messages, then a payment | interrupted (T2+), trading group |
| `task_job` | small rewards in, bigger payments out (episode events) | interrupted (T2+), task job |
| `refund_qr` | unknown caller + a QR payee | interrupted (T2+), refund QR |
| `fake_customer_care` | the user calls an unknown "helpline" + dictated typing | interrupted (T2+), fake customer care |
| `honest_users` | everyday payments: a shop, people they already pay | T0/T1, no interruption |
| `relative_emergency` (hidden) | "your son is in hospital": 9 people pay a fresh mule ₹25k each in a burst | flagged (T1+) with no playbook; shows on **Emerging patterns**; the mule is tagged **bot-scale** |

**What each agent does:** what a person's phone would really send.
1. Early warnings (`/v1/watch`).
2. Task-scam episode events (`/v1/episode`).
3. The payment check (`/v1/decide`).
4. What they did on the alert (`/v1/feedback`).
5. The outcome (`/v1/payment/outcome`).

It prints RUKO's answer next to the expected one.

**Rules.**
- Agents only test; they never take part in a decision (rule 13).
- They read the simulated world (`data/*.parquet`) only to pick users and accounts, like
  `sim.mule_pump`. The engine never does (rule 9).

**Tests:** `backend/tests/test_demo_agents.py` runs every scenario against the rules scorer. The
trained model's results are noted in `docs/ml-asks.md`.
