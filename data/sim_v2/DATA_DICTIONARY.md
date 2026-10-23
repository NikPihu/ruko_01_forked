# sim_v2 data dictionary

What every table and column means, and **when a cell is empty and why**.

**An empty cell always means "does not apply to this row"** (e.g. a shop has no mule kind). It
never means "unknown". Whether a *phone* could see a signal (consent off, old Android) is decided
later by the phone view (`ml/dataset/phone_view.py`), following CLAUDE.md rule 1.

The first columns of the 7 contract tables match `data/sim` exactly (`python -m sim_v2 validate`
checks this). Columns marked *sim_v2* are extra and sit at the end.

## Why there are no "51 feature" columns
The tables are the **raw world**: what happened. RUKO's 51 features (`backend/features/build.py`,
families C / L / P / B / S) are **computed from these tables at the moment of each payment**, using
only what existed before it. They are computed by the same code the live engine runs, so:
- **no leaks:** a stored feature could silently use the future (that's how the old simulator's
  "account age alone gives AUC 0.994" happened);
- **one world, any feature version:** when features change, rebuild the training table, not the world;
- **CLAUDE.md rule 9:** the engine never reads ground truth.

| Family | Computed from |
|---|---|
| C context (call, caller unknown / VoIP / foreign, remote app, accessibility, sideload) | `context_events`: call_started / call_ended, app_installed, remote_session_notice, accessibility_enabled before the payment |
| L lure (lure confidence and tag in 72 h; task-scam episode) | `context_events`: sms_lure / notification_lure; small credits (`scam_bait`) and outflows in `ledger` |
| P payee (holder type, verified, account age, distinct payers 6 h / 7 d, repeat ratio, pass-through, hold time, MuleHunter, registry, FRI, story mismatch) | `accounts` + the payee's rows in `ledger` (via the mock bank) + `reports` (once `listed_at` has passed) |
| B behaviour (amount vs 90-day max / median, first-time payee, typed, attempts, new-payee sum, session signs) | the payer's earlier `ledger` rows + the `pay_session` event of this payment |
| S stage (stage, minutes since first contact) | order of the journey's events before the payment |

`ml/dataset/replay.py` turns a world into the 51-column training table (one row per payment).
As of 2026-10-23 it fails on `main` because `ml/dataset/phone_view.py` imports the removed
`MoneySignal`; that's in the ml/ folder (Diwansu).

---

## ledger: every payment
| Column | Meaning | Empty when |
|---|---|---|
| `tx_id` | `t_0000000`, in time order | never |
| `ts` | time, IST (+05:30) | never |
| `from_upi`, `to_upi` | payer and payee UPI IDs (all exist in `accounts`) | never |
| `amount` | ₹, whole rupees | never |
| `entry_method` | `qr` / `typed` / `contact` (how the payee was chosen) | never |
| `flow` | `normal` everyday or look-alike · `scam` victim → mule · `scam_bait` crew → victim (rewards, fake profit) · `scam_external` outside victim → mule · `mule_forward` mule → cash-out · `mule_cover` small QR payments to a shop-disguised mule · `cashback` · `gig_payout` | never |
| `journey_id` | the scam journey this row belongs to | not part of a journey: everyday payments, look-alikes, outside victims' payments, and forwards of outside victims' money |
| `label_is_scam` | ground truth: True for `scam` and `scam_external` | never (False otherwise) |
| `label_stage` | `S4` first scam payment of a journey, `S5` later ones | every row that is not a `scam` payment |
| `scenario` *sim_v2* | why an honest payment happened: a look-alike name (`landlord_deposit`, `delivery_on_call`, …), `rent` or `bill` | ordinary everyday payments and all scam / mule rows |
| `cause_id` *sim_v2* | the decision (in `decisions`) that caused this payment | rows not caused by a logged decision (everything except victims' scam payments) |

## context_events: what happened on users' phones
| Column | Meaning | Empty when |
|---|---|---|
| `ts`, `user_id`, `event_type` | `call_started`, `call_ended`, `sms_lure`, `notification_lure`, `app_installed`, `remote_session_notice`, `accessibility_enabled`, `pay_session` | never |
| `attrs` | JSON details (same keys as `data/sim`; see contracts/README.md for `pay_session`) | never |
| `journey_id`, `label_is_scam` | the scam journey that caused the event | not caused by a scam (ordinary calls, spam SMS, look-alikes) |
| `label_stage` | S1 contacted, S2 hooked, S3 under control, S4/S5 paying | not caused by a scam |
| `scenario` *sim_v2* | look-alike that caused it | not a look-alike |
| `cause_id` *sim_v2* | the latest victim decision before this event in the journey | before the victim's first decision (e.g. the first scam call or SMS), or not a scam |

## accounts: everyone who can pay or be paid
| Column | Meaning | Empty when |
|---|---|---|
| `account_id`, `upi_id`, `mobile`, `handle`, `bank`, `partner_bank` | identity; `partner_bank` = shares payee data with RUKO's mock | never |
| `holder_name`, `holder_type` | `person` or `merchant` | never |
| `merchant_kind` | `kirana`, `pharmacy`, `hospital`, `shop`, `biller`, `platform` | people (`holder_type = person`) |
| `mcc` | merchant category code | people |
| `verified` | verified merchant | never (False for people) |
| `created_at`, `kyc_at` | account opened (equal in sim_v2) | never |
| `region` | city | never |
| `is_mule` | ground truth: a mule or cash-out account | never |
| `mule_kind` | `plain`, `rented`, `merchant_disguised`, `warm_up`, `slow_forward`, `cash_out` | every account that is not a mule |

Most accounts are not app users: they're users' contacts and landlords, shops, outside victims, and the people paying mules.

## users: people who use the RUKO app
`user_id`, `account_id`, `upi_id`, `mobile`, `region`, `age_band`, `language`, `sms_consent`, then *sim_v2*: `persona`, `income_month`, `savings_months` (what they can reach, in months of income), `call_consent`, `app_consent`, `locality`. Never empty. `age_band` and `language` are for fairness audits only, never model inputs.

## journeys: one row per scam approach
| Column | Empty when |
|---|---|
| `journey_id`, `user_id`, `playbook`, `started_at`, `n_payments`, `total_paid`, `is_demo`, `reported`, `outcome` (`completed` or `refused_at:<step>`), `crew_id`, `complied_steps` | never |
| `last_payment_at` | the victim never paid (refused before any payment) |
| `caller_number` | the playbook never called (SMS / app-notification-only scams, or stopped before the call) |
| `mule_upi_ids` | no payment was made |
| `variant` | the playbook has no variants (only `task_job` has: `rewards` / `crypto_deposit`) |

## reports: what reaches the lists
`report_id` (rows of one report share it), `identifier_type` (`upi_id` / `mobile`), `identifier`, `filed_at`, `listed_at` (= filed + listing lag), `source` (`1930`, `ncrp`, `chakshu`), `is_false`.
`journey_id` is empty for reports not tied to one of our users' journeys: outside victims' reports, bystander (Chakshu) reports and false reports.

## decisions *sim_v2*: why things happened
`decision_id` (`D_<journey>_<n>`), `ts`, `agent` (victim user or crew), `kind` (`victim`, `crew_step`, `report`), `journey_id`, `step` and `step_no` (the step's number in the playbook, 1, 2, 3, …), `inputs` (JSON: every term of the formula), `p` (probability), `draw` (random number), `outcome`.
`draw` is empty for scripted demo decisions (forced outcome). `step_no` is empty for `report` decisions (not a playbook step).

## crews *sim_v2*: mule schedule
One row per mule per slot: `crew_id`, `playbook`, `group`, `region`, `slot`, `mule_upi_id`, `mule_kind`, `active_from`, `active_to`. Never empty.

## handles
`handle`, `bank`, `app`, `partner`: the 8 UPI handles (same as `data/sim`).
