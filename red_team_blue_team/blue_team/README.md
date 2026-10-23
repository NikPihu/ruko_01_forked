# Blue team: find and name the scams RUKO missed

Owner: Diwansu Pilania. Everything lives in this folder; it only *reads* `backend/` (features,
policy, rule scorer), `ml/` (replay, trained scorer) and `data/sim_v2/` (worlds).

## The flow

| Step | Module | What happens |
|---|---|---|
| 1 Breaches | `breach.py` | Each complaint (1930 / NCRP report) is joined to the complainant's payments to the accounts it names. RUKO's tier and playbook for each payment, as the active scorer (`lgbm-0.2`) and the real policy gave them at the time. **missed** = nothing interrupted, **unnamed** = interrupted but no playbook named it, **held** = both. |
| 2 Clusters | `tokens.py`, `cluster.py` | Each missed / unnamed case becomes a token sequence (`CALL_ON CALLER_UNKNOWN SAYS_FAMILY AMT_10K_50K ... GAP_UNDER_1H PAY ...`), then TF-IDF n-grams → SVD → **HDBSCAN** (`leaf`). A cluster is *known* if most of it was already named by a playbook or its centroid is close to a playbook's cases; otherwise *new*. |
| 3 Investigator | `investigator.py`, `evidence.py`, `llm.py` | An LLM agent on **Amazon Bedrock** (Converse API with tools) reads the cluster: overview, cases, payees, known playbooks, comparisons. It tries matchers with `test_matcher` and submits a playbook card: name, story, steps, signals, matcher, reason codes, advice in English and Hindi, and whether it looks AI-powered. Code validates the card and backtests the matcher; a card failing the gates goes back to the agent (twice). |
| 4 Analyst | `analyst.py` | A second, skeptical LLM agent with the same read-only tools gives a verdict: `new_scam` / `variant_of_known` / `lookalike_not_scam` / `insufficient_evidence`. |
| 5 Humans | `review.py` | Two different analysts approve (`approvals_needed`), or one rejects with a reason. An approved card moves to `playbooks/approved/` and writes `exports/<name>/mule_accounts.csv` (for the graph suspect review) and `labels.csv` (for the next retrain). |

**The playbook database:** the *known* playbooks are the engine's own `data/playbooks/playbooks.yaml`,
read into the matcher format by `engine_file.py` (a test checks they name exactly like
`rule_scorer._playbook`); `playbooks/known/*.yaml` only add the story the agents read. `review/`,
`approved/` and `rejected/` hold the blue team's cards. `playbook_db.name_scam(features)` names a
payment: first match by priority; approved playbooks come after the known ones, except a misnamed
fix, which goes just before the playbook it corrects.

**Matchers** (`matcher.py`) are a fixed JSON rule format over engine features and two request
fields: `all` / `any` / `not` and leaves `{feature, op, value}`. The LLM can only pick features,
operators and values, so nothing it writes can run (rule 13), and an unmeasured feature never
satisfies a comparison (rule 1).

**Gates** (`config.yaml`), checked by code: the matcher names at least 60% of the cluster's cases,
at most 0.5 legit payments per 1,000, and at most 30% of known-playbook payments.

**Offline mode**: without Bedrock, the investigator is an exhaustive search over 1–3 of the
cluster's distinctive tokens (best recall that passes the gates), with template text, and the
analyst is fixed rules (IDF-weighted token profiles against known playbooks). Tests and demos
run without a key; `--llm auto` (the default) uses Bedrock when it answers.

## Run it (repo root)

```bash
export PYTHONPATH="backend;ml;data;red_team_blue_team" PYTHONIOENCODING=utf-8
.venv/Scripts/python -m pip install -r red_team_blue_team/blue_team/requirements.txt

# a world with enough breaches, replayed through the engine (about 2 + 5 minutes)
.venv/Scripts/python -m blue_team.testworld --out data/sim_v2_out/breach
.venv/Scripts/python -m dataset.replay --data data/sim_v2_out/breach --out ml/data/tables/breach.parquet --warmup-days 7

# Bedrock: put your key in the environment (never in a file in the repo)
export AWS_BEARER_TOKEN_BEDROCK=...        # PowerShell: $env:AWS_BEARER_TOKEN_BEDROCK="..."
.venv/Scripts/python -m blue_team probe    # which models in config.yaml answer

.venv/Scripts/python -m blue_team run --table ml/data/tables/breach.parquet --data data/sim_v2_out/breach
.venv/Scripts/python -m blue_team queue
.venv/Scripts/python -m blue_team show <name>
.venv/Scripts/python -m blue_team approve <name> --analyst <you> --note "..."
.venv/Scripts/python -m blue_team reject  <name> --analyst <you> --note "why"
.venv/Scripts/python -m blue_team evaluate --run red_team_blue_team/blue_team/runs/<run_id> --data data/sim_v2_out/breach
.venv/Scripts/python -m pytest red_team_blue_team/blue_team/tests -q
```

A run writes `runs/<run_id>/report.md` (what broke, the clusters, each candidate with its
backtest and both verdicts), `summary.json` and one JSON per candidate with the agents' full
transcripts. Models are tried in the order in `config.yaml` (`agents.models`) until one answers
with a tool call; `--model` picks one. No Anthropic models: on Bedrock they need a use-case form
that asks for an organisation. `probe --all --region us-east-1` (or `us-west-2`, `ap-south-1`, ...)
lists which of the open-weight models (gpt-oss, Qwen, DeepSeek, Mistral, Llama) and Amazon Nova
your account can call there; run with the same `--region`. On the first real runs Amazon Nova Pro
answered, but its own content filter blocked many replies about scams, so only 3 of 10 cards came
from the LLM.

## Results (offline agents, so a floor; seed-21 breach world, 3,000 users x 30 days)

`blue_team.testworld`: victim rate 0.5 per 60 days, emerging scams x4.

- **Where the shield broke** (lgbm-0.2 + policy): of 146 complaint cases, 49 missed and 45 unnamed.
  52 of the 76 cases of the six emerging scam types (68%) were missed or unnamed. Among the known types,
  `fake_kyc_apk` and `trading_group` were often unnamed when the phone had not seen the lure SMS.
- **Clusters**: 12 (10 new, 2 known), 22 one-off cases left as noise. Drafted clusters have mean
  purity 0.81 against the true scam type.
- **New scams found** (drafted, gates passed, analyst said `new_scam`): collect_request,
  electricity_disconnection, lottery_prize, marketplace_buyer (4 of 6). relative_emergency formed
  a mixed cluster (purity 0.5) and loan_fee had only 5 complaints.
- **Offline analyst**: 6 of 10 verdicts right. It is wrong mostly on known scams without their lure
  (fake_customer_care, task_job, trading_group called new): exactly the judgement the LLM analyst is for.
- **Closing the loop**: approving the marketplace playbook and re-running names 9 more cases, and
  that cluster comes back as *known*.
- **Second world (seed 33, not used for tuning)**: 115 cases, 7 clusters, mean purity 0.69,
  4 of 6 verdicts right, 2 of 6 emerging types found new (collect_request, marketplace_buyer).

The clustering settings were chosen on seed 21, so its numbers are optimistic; seed 33 is the
honest one. Small worlds give 4 to 10 complaints per new scam: the method needs a few weeks of
complaints before a pattern clusters.

**First LLM run (gpt-oss-120b on Bedrock, Sydney; about 0.8M tokens in, 46k out):** every card came
from the model, with real stories and multi-condition rules, but the analyst got only 3 of 10
verdicts right (offline: 6). It called known scams "new" when their lure was missing (fake_kyc_apk,
fake_customer_care, task_job, trading_group) and two of its rules failed the gates (one used
`caller_unknown is true`, which is null on VoIP calls). Changes since: rules may name tokens
(`{"token": "CALLER_UNKNOWN"}`), the analyst gets the lure-ignored similarity to each known
playbook and is told a missing lure is not a new scam, and a rule failing the gates is replaced by
the code search while the model's text is kept.

**Second LLM run, after those changes (gpt-oss-120b):** 7 of 10 verdicts right (offline 6, first LLM
run 3) and 5 of the 6 emerging scams found as new (collect_request, electricity_disconnection,
lottery_prize, marketplace_buyer, relative_emergency; loan_fee had only 5 complaints). It overrode
a 0.81 similarity to task_job after reading the cases and correctly called the voice-clone cluster
new. Still wrong: trading_group (no complaint in this world was named trading_group, so its
similarity read 0; it now says "unknown"), task_job (the investigator never submitted) and
fake_customer_care. These prompts were improved on this world, so check them on `breach_s33`.

**Held-out check (seed 33, gpt-oss-120b, prompts not tuned on it):** the analyst got 6 of 6 verdicts
right (some clusters were mixed, purity 0.33 to 0.5), but only 2 of the 6 emerging scams were found
(collect_request, marketplace_buyer). The rest never reached the blue team: 11 of the 16
relative_emergency (voice-clone) complaints were *held*, interrupted but named digital_arrest, so
the user got the wrong advice; 9 collect_request complaints were also named digital_arrest and 6
marketplace_buyer ones refund_qr; electricity, loan and lottery had 1 to 3 complaints each.
**Misnamed check (built after this):** complaints RUKO interrupted *and* named, whose victims still
paid, are now checked too (`cluster.misnamed`). Each playbook's held complaints are clustered on
their own; subgroups that do not fit the rest (`misnamed.fit_below`) go to the agents with
"RUKO named these X; is that right?". An approved fix runs just *before* X (`misnamed_as`,
`playbook_db.priority_before`), so its rule must pick out only that subgroup; `test_matcher` counts
the other X payments it would take. Suspected-misnamed cases no longer define what X looks like
when deciding whether a breach cluster is known (they made missed voice-clone calls look like
digital arrests). The fit number did not separate real from misnamed subgroups on either world
(0.65 to 0.76 for both), so code only proposes and the agents judge. Offline, the groups are right
(collect_request and voice-clone calls named digital_arrest; refund_qr named digital_arrest; one
real digital-arrest group) but the offline analyst judged only 2 of 5 and 2 of 3 of them correctly.
Also fixed: `named_main` broke ties by set order, so clusters changed between runs (PYTHONHASHSEED).

**First LLM run with the misnamed check (gpt-oss-120b):** breach clusters 5/6 right on seed 33 and
6/10 on seed 21; misnamed groups 1/3 and 3/5. It said "correctly named" for both real
digital-arrest groups and found a refund_qr group RUKO called digital_arrest, but it kept calling
the voice-clone / collect-request groups "variant of digital_arrest", citing that digital_arrest's
rule matched 86% of them: circular, since that is how they were selected. Now `compare_with_playbook`
hides that number for the group's own playbook and returns the playbook's story instead, both
agents are told to judge misnamed groups by the story (payer_says, caller, remote control, entry,
amounts), and temperature is 0 so runs can be compared.

**After that fix (gpt-oss-120b, temperature 0):**

| World | New-scam clusters right | Misnamed groups right | Emerging scams found new |
|---|---|---|---|
| seed 33 (prompts never tuned on it) | 5/6 | 2/3 (was 1/3) | collect_request, marketplace_buyer |
| seed 21 | 6/10 | 4/5 (was 3/5) | collect_request, electricity_disconnection, lottery_prize, relative_emergency |

Misnamed verdicts went from 4/8 to 6/8 across both worlds. Remaining errors: known scams without
their lure still called new (fake_customer_care twice, task_job, trading_group); one voice-clone /
collect mix still called digital_arrest, where the investigator wrote an "arrest threat" story the
cases do not show. Both worlds have only 4 to 16 complaints per group, so one verdict moves the
score by 10 to 30 points: read these as "works, with errors", and keep the two-analyst review.

The agent loop itself is tested with a scripted fake Bedrock client (`tests/`).

## What other folders need (not done here)

How an approved playbook goes live: `approve` (two analysts) writes
`exports/<name>/playbooks_entry.yaml`, an entry for the engine's `data/playbooks/playbooks.yaml`
(api/playbooks.py format) with where it goes: at the end, or for a *misnamed* fix just before the
playbook it corrects. Someone pastes it into the file and the engine names that scam from then on.
The blue team reads the engine's file for the known playbooks, so it never judges against a stale copy.

**Jagdeep (backend):**
1. **Blocker: open the scam-name list in the contract.** `Threat.fraud_type` and
   `DeviceVerdict.fraud_class` are `FraudType`, a fixed list of six names (c2-0.10), and `threat.fraud_type`
   is the playbook. So *any* new name in `playbooks.yaml` (from the blue team, or from naming an A4
   emerging pattern) fails validation when the `/v1/decide` response is built. Make it a string
   (snake_case), or keep the list but map unknown names to `null` plus a new `scam_name` field.
   Rule 8: version bump, examples, Models.kt, ContractTest.
2. **Extend the playbooks-0.1 format** so blue-team rules fit. Of the 24 cards gpt-oss drafted in the
   two test worlds, 3 export as they are; the rest need:
   - the request fields `entry_method` (20 cards) and `payer_says` (6) as match keys (they are in
     every `/v1/decide` request but are not `FAMILY` features);
   - number comparisons, e.g. `amount_inr: {gte: 10000, lt: 50000}` (`>=` in 17 cards, `<` in 7);
     the blue team's ops are `>=`, `<=`, `>`, `<`; unknown (null) must never satisfy them (rule 1).
   `engine_file.export_entry` lists exactly what is missing for each card, and
   `tests/test_matcher_and_db.py` checks an exported entry names payments exactly like the matcher.
3. **Message text for new names.** The app shows `<tier>_<name>` strings from AlertText.kt and falls
   back to the tier's generic text. An approved card carries `advice_en` / `advice_hi`; either ship
   them in the response (with item 1) or add them to AlertText.kt per playbook.
4. **Mule accounts:** `exports/<name>/mule_accounts.csv` as seeds for `graph/discover.py`'s suspect
   review (still two analysts, rule 11), e.g. `POST /v1/graph/suspects/import`.
5. **Emerging patterns (your A4) and the blue team** look at different moments: A4 groups flagged
   and near-miss payments *before* a loss; the blue team groups 1930 / NCRP complaints *after* one,
   including interruptions that named the wrong scam. Both draft entries in the same file format,
   so they can share the review step. Optional: send an A4 pattern to the blue team's investigator
   for a story and a backtested rule.
6. Optional: a console page for `playbooks/review/` instead of the CLI.

**Manjeet (android):** after item 1, show a scam name the app has no strings for, using the advice
text from the response.

**Diwansu (ml):** read `exports/*/labels.csv` in `model/train.py` as extra labels for the next retrain.

**Nikunj or the red team:** AI-powered scam variants as `emerging` sim_v2 playbooks (`../red_team/README.md`).

**CLAUDE.md:** add `red_team_blue_team/` to "Who owns what" (owner: Diwansu), and say the blue team
needs `PYTHONPATH=backend;ml;data;red_team_blue_team` and `requirements.txt` (boto3).
