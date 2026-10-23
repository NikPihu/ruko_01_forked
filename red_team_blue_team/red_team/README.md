# Red team

Not built yet. The blue team currently uses the six scam types that `data/sim_v2` marks
`emerging` (RUKO has no playbook for them) as its red team:

| sim_v2 playbook | What it is |
|---|---|
| `collect_request` | "approve this request / enter your PIN to receive the money" (UPI collect abuse) |
| `electricity_disconnection` | "your electricity will be cut tonight, call this officer" SMS, a call, a screen-share app |
| `loan_fee` | "pre-approved instant loan": processing, insurance and GST fees before a disbursal that never comes |
| `lottery_prize` | "you won the KBC / company lottery": processing, tax and transfer fees first |
| `marketplace_buyer` | fake buyer on OLX / Marketplace: a small "test" payment by QR, then a large one |
| `relative_emergency` | voice-clone call: "Papa, I've been arrested / had an accident, send money now" |

`python -m blue_team.testworld` builds a world where these are common enough to cluster.

## What the red team should add

New scams as sim_v2 playbook YAML (see `data/sim_v2/config/playbooks/README.md`; a new file is
picked up with no code change), marked `emerging: true`, ideally AI-powered variants:

- voice-clone relative with a video call (deepfake) and a hospital story;
- an AI chatbot "customer care" that dictates amounts in short bursts;
- deepfake video-KYC "bank officer" asking for a screen share;
- variants that dodge today's signals: ending the call before paying, splitting into small
  tranches, paying by QR instead of typing, using an old mule account.

The blue team needs nothing else: it reads only the world's tables and the complaints
(`reports.parquet`), exactly as it would read real 1930 / NCRP complaints.
