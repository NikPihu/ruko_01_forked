# Blue team: find and name the scams RUKO missed

Owner: ML. Everything lives in this folder; it only *reads* `backend/` (features,
policy, rule scorer), `ml/` (replay, trained scorer) and `data/sim_v2/` (worlds).

## The console (start here)

```bash
export PYTHONPATH="backend;ml;data;synthetic_playbook;red_team_blue_team" PYTHONIOENCODING=utf-8
export AWS_BEARER_TOKEN_BEDROCK=...        # optional: without it runs are offline (no LLM)
.venv/Scripts/python -m blue_team app      # -> http://127.0.0.1:8765
```

Four tabs that follow the loop, left to right, plus a Live check panel (design and data sources:
`docs/design/red-blue-console/README.md`). Every decision keeps its reason and its references; the
long views (agent turns, run log, a playbook's script) open in a side drawer.

| Tab | What you see |
|---|---|
| Overview | the loop (Attack, Investigate, Playbooks, Live check: one number and a state each; the step waiting for a person is orange), **scam groups** (`GET /api/groups`, `groups.py`: the red team's attacks per kind of scam, never one total: got through, called normal, complaints, the group's playbook and its sign-off), what is waiting for you, and the scorecard (the only view that uses the simulator's answer key) |
| 1 Attack | run the attack runner (`synthetic_playbook/interface_script`) over a playbook set against the real engine (resumable), **Generate** new playbooks (`red_team/cli.py` into the `generated` set), attacks by group with their tricks, and one attack in detail (`GET /api/redteam/playbooks/{name}/detail`: called normal, where in the scam RUKO lost it, the threat-score histogram, why the caught ones were flagged, its script). "Hand N breakthroughs to the blue team" builds the attack world (sim_v2 + replay) |
| 2 Investigate | start a blue-team run (world, Bedrock or offline, Reset everything) and its log; the run's progress (complaints → got past RUKO → grouped → drafted → checked → people); the HDBSCAN groups and misnamed? groups; the selected group's map, shared signals, money lost, two closest known playbooks, the agents' turns, and its complaints with every payment as RUKO saw it |
| 3 Playbooks | the review queue and the library in one table (waiting / live / rejected; catches, honest per 1,000, warns or names only, sign-off), the engine's live list; each playbook's page says **why it was chosen**: the trail from the complaints to the sign-off, the rule condition by condition (share of the group's complaints and honest payments per 1,000 for each), the group against the two closest known playbooks signal by signal, the warning in English and Hindi, the stored YAML, sign-off (two different analysts, a note to reject, edit text) and, once approved, Verify |
| Live check | the demo (`scenario.py`, console started with `--scenario`): build world → round 1 → review → round 2, scam payments interrupted and honest interruptions per 1,000 before → after, per scam type with why the rest got through |

Old links (`#/complaints`, `#/hdbscan`, `#/run`, `#/scorecard`, `#/generator`, `#/analyst`, `#/database`,
`#/demo`, `#/redteam`) open their new place.

## The flow

| Step | Module | What happens |
|---|---|---|
| 1 Breaches | `breach.py` | Each complaint (1930 / NCRP report) is joined to the complainant's payments to the accounts it names. RUKO's tier and playbook for each payment, as the active scorer (`lgbm-0.2`) and the real policy gave them at the time. **missed** = nothing interrupted, **unnamed** = interrupted but no playbook named it, **held** = both. |
| 2 Clusters | `tokens.py`, `cluster.py` | Each missed / unnamed case becomes a token sequence (`CALL_ON CALLER_UNKNOWN SAYS_FAMILY AMT_10K_50K ... GAP_UNDER_1H PAY ...`), then TF-IDF n-grams → SVD → **HDBSCAN** (`leaf`). A cluster is *known* if most of it was already named by a playbook or its centroid is close to a playbook's cases; otherwise *new*. |
| 3 Investigator | `investigator.py`, `evidence.py`, `llm.py` | An LLM agent on **Amazon Bedrock** (Converse API with tools) reads the cluster: overview, cases, payees, known playbooks, comparisons. It tries matchers with `test_matcher` and submits a playbook card: name, story, steps, signals, matcher, reason codes, advice in English and Hindi, and whether it looks AI-powered. Code validates the card and backtests the matcher; a card failing the gates goes back to the agent (twice). |
| 4 Analyst | `analyst.py` | A second, skeptical LLM agent with the same read-only tools gives a verdict: `new_scam` / `variant_of_known` / `lookalike_not_scam` / `insufficient_evidence`. |
| 5 Humans | `review.py`, `webapp.py` | **Review page** (`python -m blue_team app` → http://127.0.0.1:8765): each drafted playbook in full (story, steps, warning in English and Hindi, rule and backtest, the analyst agent's verdict and reasons, example complaints, mule accounts, whether the engine can take it yet). Analysts can fix the text (an edit clears earlier approvals), approve or reject (a reason is required). Two different analysts approve (`approvals_needed`); the card then moves to `playbooks/approved/` and writes `exports/<name>/`: the entry for `data/playbooks/playbooks.yaml`, `mule_accounts.csv` (for the graph suspect review) and `labels.csv` (for the next retrain). The same steps work on the command line. |

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
export PYTHONPATH="backend;ml;data;synthetic_playbook;red_team_blue_team" PYTHONIOENCODING=utf-8
.venv/Scripts/python -m pip install -r red_team_blue_team/blue_team/requirements.txt

# a world with enough breaches, replayed through the engine (about 2 + 5 minutes)
.venv/Scripts/python -m blue_team.testworld --out data/sim_v2_out/breach
.venv/Scripts/python -m dataset.replay --data data/sim_v2_out/breach --out ml/data/tables/breach.parquet --warmup-days 7

# Bedrock: put your key in the environment (never in a file in the repo)
export AWS_BEARER_TOKEN_BEDROCK=...        # PowerShell: $env:AWS_BEARER_TOKEN_BEDROCK="..."
.venv/Scripts/python -m blue_team probe    # which models in config.yaml answer

.venv/Scripts/python -m blue_team run --table ml/data/tables/breach.parquet --data data/sim_v2_out/breach
.venv/Scripts/python -m blue_team app      # review page: http://127.0.0.1:8765
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

## After approval: does RUKO now catch it? (`verify.py`)

Two analysts approving says the story and rule look right; **Verify** (Playbooks page, on an approved
card, or `python -m blue_team verify <name> [--offline-only] [--retrain]`) measures what approving it
changes. A playbook only **names** a scam (the warning's words and `threat.fraud_type`); **interrupting**
(T2+) comes from the model, so the checks keep the two apart:

| Check | Time | What it answers |
|---|---|---|
| 1 named, offline | seconds | The engine's playbook file plus this entry (checked by the engine's own parser) over the card's world: share of the scam's payments named, on its own complaints and on payments **nobody complained about** (answer key, evaluation only), legit payments named per 1,000, payments taken from a known playbook. A rule the file format cannot express is measured with the blue-team matcher and flagged |
| 2 live | ~5 min | the attack runner on the scam's playbooks in a fresh world (`verify.seed`), judged by the engine as it is, with the entry pasted into its file (`RUKO_PLAYBOOKS`), and a **preview** with the rule in the engine's namer and the contract open to new names (`verify_engine.py`). Named, interrupted, called-normal, fail-open, before vs after |
| 3 retrain | +~10 min | LightGBM retrained on its own training table plus the card's complaint-labelled payments into `exports/<name>/model/` (v0 untouched), then check 2's world again with `RUKO_MODEL` |

Verify runs never write the red-team inbox (the runner's blue-team sink is dropped) or anything in
`backend/`, `data/` or `ml/model/artifacts/`. Results: `exports/<name>/verify.json`.

What it found on the first cards: before playbooks-0.2, a playbook only *named* a scam and the engine
showed the name only at T1+, so an approved playbook changed nothing for a victim LightGBM scored T0
(live: named 43% of a red-team scam inside the engine, 0% shown, 0% interrupted). Hence the policy
step below. It also catches overfitting: `qr_dictated_payment_scam` (LLM run) named 75% of its own
complaints but 0% of the same scam's payments nobody complained about.

## What other folders need (not done here)

How an approved playbook goes live: `approve` (two analysts) writes
`exports/<name>/playbooks_entry.yaml`, an entry for the engine's `data/playbooks/playbooks.yaml`
(api/playbooks.py format) with where it goes: at the end, or for a *misnamed* fix just before the
playbook it corrects. Someone pastes it into the file and the engine names that scam from then on.
The blue team reads the engine's file for the known playbooks, so it never judges against a stale copy.

**Backend: done on this branch, please review** (`backend/api/playbooks.py`, `policy.py`,
`policy.yaml`, `main.py`, `rule_scorer.py`, `tests/test_approved_playbooks.py`):
1. **Approved playbooks warn.** An entry with `approved_by` (two different analysts) makes policy raise
   its payments to at least T2 (`policy.yaml` `approved_playbooks`), even when LightGBM scored them
   low, which it does for scams it never saw. Rule 5 holds: the entry's own conditions must span two
   families (`playbooks.families`); amount caps, trusted payees and the alert budget apply after it.
   A rule made only of behaviour signals still just names the scam.
2. **No fail-open on a new name.** `threat.fraud_type` stays the contract's six names; a newer name goes
   out in `playbook` and the message key only (before, it failed the response and the engine failed
   open). No contract change: the app shows the tier's generic words until item 3.
3. **playbooks-0.2 format:** number comparisons (`amount_inr: {gte: 1000, lt: 10000}`, unknown never
   matches, rule 1), the request fields `entry_method` / `payer_says`, and `approved_by`. 48 of the 49
   cards drafted so far export (was 3); 17 of them warn, the rest only name.
4. **Message text for new names.** The app shows `<tier>_<name>` strings from AlertText.kt and falls
   back to the tier's generic text. An approved card carries `advice_en` / `advice_hi`; either ship
   them in the response (with item 1) or add them to AlertText.kt per playbook.
5. **Mule accounts:** `exports/<name>/mule_accounts.csv` as seeds for `graph/discover.py`'s suspect
   review (still two analysts, rule 11), e.g. `POST /v1/graph/suspects/import`.
6. **Emerging patterns (your A4) and the blue team** look at different moments: A4 groups flagged
   and near-miss payments *before* a loss; the blue team groups 1930 / NCRP complaints *after* one,
   including interruptions that named the wrong scam. Both draft entries in the same file format,
   so they can share the review step. Optional: send an A4 pattern to the blue team's investigator
   for a story and a backtested rule.
6. Optional: a console page for `playbooks/review/` instead of the CLI.

**Android:** after item 1, show a scam name the app has no strings for, using the advice
text from the response.

**ML:** read `exports/*/labels.csv` in `model/train.py` as extra labels for the next retrain.

**Attack runner (`synthetic_playbook/interface_script/sinks.py`):** this branch adds one sink, `blue_team`, to
his `SINKS` list. It does nothing when `red_team_blue_team` is not on the path, so his runner works as
before without the blue team.

**The red team:** AI-powered scam variants as `emerging` sim_v2 playbooks (`../red_team/README.md`).

**CLAUDE.md:** add `red_team_blue_team/` to "Who owns what" (owner: ML), and say the blue team
needs `PYTHONPATH=backend;ml;data;red_team_blue_team` and `requirements.txt` (boto3).
