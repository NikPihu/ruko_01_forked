# Plan v3: lure classifier with "unclear", step-based verdicts, playbook search, one fused threat score, lgbm-0.3 on large data

Status: steps 0-5 built and live (contract c2-0.14, now c2-0.15); step 6 in progress, step 7's
report is the Results section below. See "Results (25 Oct 2026)" for what changed from this plan.

## Why
- **The lure classifier must answer from six fixed classes.** A message that is neither a known scam
  nor clearly normal is forced into the nearest class, or quietly scored low.
- **The phone's verdict and the playbooks speak different languages.** The verdict gives
  family scores plus one fraud class. The playbooks are hand-written rules over features. Neither
  says which **steps** of a scam were seen.
- **A playbook can only name a scam, never raise its risk, and new scams match nothing.** The playbook
  matcher is "first rule that matches", with no similarity.
- **Tiers come only from LightGBM's score, gated by "two families lit"** (rule 5). New scams with one
  strong family get T0. A strong playbook match cannot raise the tier.
- **lgbm-0.2 trained on one 5,000-user world.** It never saw the attack playbooks or 9 of today's 63
  engine features.

## The decisions (agreed)
1. **Policy:** one **fused threat score** (LightGBM + playbook search). Tiers come from that score.
   Only a few guardrails remain: tiny amounts, "I know this person", alert fatigue, fail-open. The
   "two families lit" gate goes away; CLAUDE.md rule 5 is rewritten.
2. **Playbook search:** **step vectors** in one shared step vocabulary. It is deterministic,
   explainable, takes under 5 ms and runs on the phone too. No LLM in the decision path (rule 13).
3. **Data:** about **200,000 users** in independent world shards, plus held-out shards and held-out
   attack playbooks.
4. **Names:** no people's names in code, UI, docs or file names. CLAUDE.md's "Who owns what" table
   stays.

---

## Step 0: groundwork (½ day)
- **Names.** Remove people's names from code, comments, console text, READMEs and file names:
  - "<name>'s runner" → **attack runner**;
  - the attack playbooks' notes → `red_team/ATTACK_PLAYBOOKS.md`;
  - their claimed scores → `attack_manifest.csv`;
  - `redteam.py` `CLAIMS` path, console strings, `config.yaml` comments;
  - `ml/PLAN.md` header ("Owner: …" → "Owner: ML").

  `grep -ri` over the repo shows none left (a test checks it).
- **One shared step vocabulary: `contracts/steps.json`** (see Step 2), so the phone, the playbooks,
  the server and the blue team use exactly the same step names.
- **Fix the open items:**
  - finish the stopped `dev`/`dev_test` replays;
  - merge PR `ml/lgbm-0.3` (the runner clock fix) first, because every evaluation below depends on it.

## Step 1: lure classifier lure-0.2, with "unclear" and "other_scam" (1–1.5 days)
**Today:** 6 classes (arrest_threat, kyc, task_job, trading_tip, refund, normal), 3,643 texts (1,612
normal). Held-out F1 for `refund` is only 0.21.

**Change:**
- **Classes:**
  - the 5 known scam tags;
  - **`other_scam`**: scams outside the five, e.g. courier/customs, electricity cut-off, lottery,
    loan fee, society maintenance, fake job fee, sextortion;
  - **`normal`**.
- **"unclear" is a decision, not a trained class.** If **no class reaches 0.6** (the same threshold
  every class uses: `SEND_THRESHOLD`), the answer is `unclear` with the top class and its confidence
  attached. "Not sure" is never reported as "normal" (rule 1).
- **Corpus `ml/model/lure_corpus.py` → about 25,000 texts, at least 55% normal:**
  - **everyday normal:** OTPs, bank debit/credit alerts, deliveries, recharges, bills, doctor and
    school messages, family chat in EN, HI and Hinglish, promos;
  - **hard look-alikes:** real KYC reminders, real refunds, police awareness SMS;
  - **`other_scam` templates.**

  Every row keeps its template id.
- **Training:** keep char n-gram TF-IDF + logistic regression (cheap on a phone).
  `class_weight="balanced"`, then a temperature-calibration step so that 0.6 means the same thing for
  every class. Choose C on held-out templates.
- **Acceptance, on held-out templates:**
  - normal → scam false alarms ≤ 0.5%;
  - scams caught (any scam class, or unclear) ≥ 85%;
  - unclear rate on normal ≤ 3%;
  - `refund` F1 ≥ 0.6;
  - per-language report (EN / HI / Hinglish).
- **Outputs:** `ml/model/artifacts/lure.json` (lure-0.2) + `lure_vectors.json`, which includes
  unclear cases.
- **Phone:** `LureScorer.kt` gets the new classes and the unclear rule. `LureModelTest` checks the
  vectors.
- **Contract c2-0.14:**
  - `LureTag` gains `other_scam` and `unclear`;
  - `WatchEvent` and `context.lures` accept them;
  - schema export, examples, `Models.kt`, `ContractTest` (rule 8).

## Step 2: the step vocabulary, and a verdict made of steps (2 days)
**`contracts/steps.json`** lists every step a scam can show, grouped the way a playbook reads.
`known_by` says who can see the step; unknown steps stay unknown (rule 1).

| Stage | Steps (examples) | Seen by |
|---|---|---|
| contact | `unknown_call`, `voip_call`, `video_call`, `call_out_to_unknown`, `long_call`, `foreign_call` | phone |
| lure | `lure:arrest_threat`, `lure:kyc`, `lure:task_job`, `lure:trading_tip`, `lure:refund`, `lure:other_scam`, `lure:unclear`, `chat_lure` | phone |
| hook | `bait_credit`, `episode_watching`, `episode_active`, `escalating_payments` | phone |
| control | `remote_control`, `screen_recorded`, `untrusted_accessibility`, `sideload_24h` | phone |
| coaching | `dictated_amount`, `paste_after_switch`, `many_app_switches`, `long_hesitation`, `abandoned_tries` | phone |
| payment | `new_payee`, `qr_entry`, `contact_entry`, `typed_entry`, `amount_unusual`, `amount_under_1k`, `amount_10k_plus`, `repeat_attempts`, `paid_after_call` (cool-off), `anchor_then_drain`, `outflow_burst` | phone + server |
| payee | `young_account`, `many_payers`, `pass_through`, `mulehunter_high`, `registry_listed`, `new_and_spreading`, `in_campaign`, `ring_member`, `automated` | server |

Each step has a fixed definition over existing measurements, in one Python module and its Kotlin
port, checked by shared vectors. Example: `paid_after_call` = no call now and a call with an unknown
number ended 5–180 minutes ago.

**Device verdict v2 (c2-0.14, additions only, so older apps still validate):**
- `steps_seen`: the phone-side steps observed in this journey, with minutes ago, e.g.
  `[["unknown_call",42],["lure:other_scam",130],["dictated_amount",0]]`.
- `steps_unmeasured`: the step groups the user switched off.
- The scores `c` / `l` / `b`, the level and the reasons stay. `fraud_class` stays for older servers.

**Code:**
- `ml/dataset/steps.py` (reference) and `android/.../signals/Steps.kt` (port);
- `ml/model/device/verdict.py` and `DeviceVerdict.kt`;
- `contracts/examples/steps_vectors.json` (shared vectors);
- tests on both sides.

## Step 3: playbooks written as steps, and the playbook search (2 days)
**Playbook format `playbooks-0.3`:** every playbook is a list of **steps with weights**, required or
optional, plus the warning words:

```yaml
- name: digital_arrest
  steps:
    - {step: unknown_call, weight: 2, required: true}
    - {any: [remote_control, video_call, dictated_amount], weight: 2, required: true}
    - {step: lure:arrest_threat, weight: 1}
    - {step: amount_10k_plus, weight: 1}
    - {step: new_payee, weight: 1}
  approved_by: [...]          # blue-team playbooks
```

**Which playbooks:**
- the six known ones, rewritten in steps;
- blue-team approved ones: the blue team drafts steps instead of matchers, so `engine_file.export_entry`
  writes steps;
- the attack playbooks: translated to steps automatically from their scripts, for **evaluation only**,
  never loaded by the engine.

**Search** (`backend/api/playbook_search.py`, under 5 ms, no network):
- The payment's step set = the phone's `steps_seen` + the server's own steps (payee, payment, graph).
- For each playbook:
  - `coverage` = weighted share of its steps that were seen, with IDF weights so common steps like
    `new_payee` count little;
  - if a required step is missing (seen as false), the score is 0;
  - if a required step is unmeasured, it is left out of both the numerator and the denominator, and
    capped (rule 1: unknown is never safe, and never proof either).
- **Output:** the top 3 playbooks with similarity, **matched steps and missing steps** (the
  explanation), and `p_playbook`, an isotonic map from similarity to P(scam) fitted on training
  worlds.
- **Fallback:** the old first-match matcher stays for the file format checker. `GET /health` reports
  `playbook_search: steps-0.1`.

The blue team's Verify and Live check report similarity and matched/missing steps too.

## Step 4: lgbm-0.3 on about 200,000 users (training ½ day + replay 3–4 hours)
**Data** (`ml/dataset/worlds.py` + `redteam_worlds.py`, sharded):
- **Training:** 32 shards × 5,000 users × 60 days. Each shard is old-simulator style or sim_v2, with
  different seeds, all known scams, and **the training half of the attack playbooks**.
- **Calibration:** 4 shards (thresholds, fusion, playbook isotonic).
- **Test:** 4 shards with **the other half of the attack playbooks**, never trained on.
- Replays run in parallel (12 cores, about 3–4 hours). Then `ml/data/tables/v3/<shard>.parquet`.
  Training reads shards lazily (`model.train --table ml/data/tables/v3/train_*.parquet`).

**Inputs:**
- all 63 engine features (incl. MuleHunter, payment-graph, campaign, anchor and outflow signals);
- **the verdict converted:** `device_c/l/b`, `device_level` (one-hot), `device_fraud_class` (one-hot),
  `steps_seen` (multi-hot over the vocabulary), `lure` class + confidence + `unclear`.

**Not an input:** playbook similarity. It is fused afterwards, so the two stay independent evidence.

**Model:**
- **one LightGBM over all inputs** for `p_lgbm`, since the per-family gate is gone;
- keep the per-family contribution split (`pred_contrib` summed per family) for the analyst view and
  the reasons;
- verdict dropout stays (30%);
- early stopping on the calibration shards; isotonic calibration.

**Acceptance, through the new policy, on the test shards:**
- held-out attack playbooks: scam payments interrupted ≥ 2× lgbm-0.2;
- known scams: no worse than lgbm-0.2;
- honest interruptions ≤ 2 per 1,000;
- per age-band gap reported (rule 14 audit);
- live: the attack runner (clock fixed) on the 25 held-out playbooks, breakthroughs before → after.

**Promotion:** replace `ml/model/artifacts/v0/server_model.json` (agreed), with `MODEL_VERSION`,
CLAUDE.md, PLAN.md and the `ServerStatus` example updated.

The on-device model is retrained the same way (`device-0.2`) on the same shards, with the step
features.

## Step 5: one fused threat score and a slim policy (1 day)
**Fusion** (`backend/api/threat.py`):

```
threat = 1 - (1 - p_lgbm) * (1 - p_playbook)        # either strong is enough; both strong is stronger
```

The weights are refit on the calibration shards: a small logistic fit over (logit p_lgbm,
logit p_playbook, their product). The noisy-OR form above is the default if the fit is not better.

**Tiers** from `threat` alone, with thresholds in `policy.yaml` (`tiers: T1 0.30 / T2 0.55 / T3 0.80 /
T4 0.92 + registry hit`). They are tuned on the calibration shards for a budget of ≤ 2 honest
interruptions per 1,000.

**Guardrails kept** (`policy.yaml`, all applied after the tier):
- under ₹200 → at most T1;
- "I know this person" → T0, unless a registry hit or screen control (unchanged);
- alert budget (unchanged exceptions);
- fail-open (rule 3);
- analyst-approved mule → at least T3.

**Removed:** the "two families lit" gate (rule 5) and family-count tier rules.

**Response** (no contract break: same fields, more inside `threat`):
- `threat.score` = round(100 × threat);
- new fields `threat.parts {lgbm, playbook}`, `threat.playbook {name, similarity, matched, missing}`;
- `fraud_type` = the top playbook if its similarity is above the naming bar, for any tier ≥ T1.

The app still shows only words (rule 4).

**Docs:** CLAUDE.md rules 5 and 13 and the "Which scorer runs" section; `docs/flows.md`;
`docs/features/threat.md`.

**Tests:**
- fused score properties: monotonic, either-high, both-higher;
- guardrails;
- the old Meena / kirana / coached examples keep their tiers;
- new: one strong family + a playbook match → T2+.

## Step 6: the console and the blue team on the new pieces (1 day)
- Review shows steps, not matcher chips. Verify and Live check show `p_lgbm`, `p_playbook`, the
  fused threat and matched/missing steps per payment.
- The blue team drafts **steps** for new scams (generator agent prompt + offline step search). The
  gates are measured on **payments**, not complaints.
- The attack runner reports `threat.parts` per playbook.

## Step 7: evaluation and handover (½ day)
- One report in `ml/runs/v3_report.md`, in plain words:
  - known scams, held-out attack playbooks, honest false alarms per 1,000, by age band;
  - before/after table: lgbm-0.2 + old policy → lgbm-0.3 + fusion.
- CLAUDE.md and PLAN.md numbers updated. One PR per owner area:
  1. contract + steps;
  2. backend search + policy;
  3. Android lure/steps/verdict;
  4. ml models + data;
  5. blue team + console.

  Each PR has its tests green (backend, ml, interface_script, blue team, Android unit tests).

## Results (25 Oct 2026)

Steps 0-5 are built; lgbm-0.3+pg1, its fusion and device-0.2 are live in `ml/model/artifacts/v0/`.
Step 6 (console and blue team on steps) is the red / blue console redesign (`feature/rb-console`);
the blue team's approved playbooks are not yet written as steps.

**Data:** 40 world shards (`ml/dataset/shards.py`), 3.35 M payments, 28,831 scam payments: 32 train,
4 calibration, 4 test; the test shards hold the 25 attack playbooks no training shard has.

**Held-out test shards, through the real policy** (`model.evaluate --fusion`):

| | lgbm-0.2 + device-0.1 | lgbm-0.3 + device-0.2 + fusion |
|---|---|---|
| 25 unseen attack playbooks, scam payments interrupted (mean) | 4.3% | **93.4%** (lowest 52%) |
| Known scams, sim / sim_v2 world | 98.1% / 66.3% | 100% / 94.3% |
| Honest interruptions per 1,000, sim / sim_v2 | 0 / 0.42 | 1.46 / 0.41 (limit 2) |
| Age-band gap in honest interruptions (rule 14 audit) | – | 1.42 / 1.73 |
| On-device warnings on honest payments per 1,000, sim_v2 | 0.77 | 0.03-0.05 |

Where the gain comes from (sim_v2 test world): lgbm-0.3 alone, under the old two-families gate,
interrupts 71% at 0.00 honest per 1,000; the fused playbook search adds about 20 points for 0.4 honest
per 1,000.

**Decisions made on the data:**
- **Four family models, not one.** A single LightGBM over every input (the first design) took a
  shortcut in these worlds: a dictated amount plus a mule-like payee separate nearly every scam, so it
  gave a call with screen control almost no weight (a Meena-like payment without session data scored
  0.0003). It also failed the honest budget (2.9-3.9 per 1,000). Each family model must learn from its
  own evidence; `ml/tests/test_train_v3.py` keeps the comparison.
- **Combiner weights >= 0.** An unconstrained fit weighed the call family negatively.
- **The two models ship as a pair.** lgbm-0.3 trained on device-0.1's verdicts gave 4.8 honest per
  1,000 when the phone sent device-0.2's; it was retrained on the shards re-verdicted with device-0.2
  (a pure function of the stored phone features, so equal to a re-replay).
- **Playbook search:** every required step must be seen (one seen required step matched 76% of honest
  payments to refund_qr); a stranger's credit cannot anchor task_job (29% of honest payments have one).

**Read with care:** the "unseen" playbooks are new scripts from the same simulator as the training
half; lgbm-0.2 had never seen that simulator. Real-world gains will be smaller
(`data/eval/realism/FINDINGS.md`). Known gap: `features/build.py` sets `outgoing_to_unknown` to false
when the caller's contact status is unknown (rule 1); fix it with the next retrain.

## Order and dependencies
```
0 groundwork ──► 1 lure-0.2 ──┐
               └► 2 steps + verdict ──► 3 playbook search ──┐
                                   └──► 4 big data + lgbm-0.3 ──► 5 fusion + policy ──► 6 console/blue team ──► 7 report
```
Steps 1 and 2 can run in parallel. The 3–4 hour replay (Step 4) starts as soon as Step 2's step
features exist in the replay.

## Risks
- **Contract c2-0.14 touches the app.** The Kotlin ports must match the Python reference exactly.
  Shared vectors are the guard; Android tests run with the JBR toolchain.
- **Dropping "two families" can raise false alarms.** The budget (≤ 2 per 1,000) is enforced by
  tuning on calibration shards and checked on the test shards before anything ships.
- **The simulator is still easy** (`data/eval/realism/FINDINGS.md`). Held-out attack playbooks are
  the honest test; their numbers are the ones to quote.
- **200k-user replay time.** If the payment graph slows it down (a known issue), shard further.
