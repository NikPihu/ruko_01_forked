# Fused threat: one score from the model and the playbook search

**What it does.** Decides how risky a payment is, as one probability, from two independent kinds of
evidence:
- **the trained model's** `p_scam` (`lgbm-0.3+pg1`: four family models and a combiner, see
  CLAUDE.md "Which scorer runs");
- **the playbook search:** how closely the journey's scam steps match a known scam written in steps
  ([playbooks.md](playbooks.md), "Playbook search").

The tier (T0 to T4) comes from this fused score. Since plan v3 step 5 it replaces the "two families
lit" gate whenever the trained model and its fusion file are loaded (CLAUDE.md rule 5).

**Where.**
- `backend/api/threat.py`: the fusion at decision time (no network, well under 1 ms).
- `ml/model/fusion.py`: fits it on the calibration shards and writes `ml/model/artifacts/v0/fusion.json`.
- `backend/api/policy.py` + `policy.yaml` `fused:`: tiers from the score, then the guardrails.
- `backend/api/main.py` (`decide_inner`): runs the search, fuses, hands the result to the policy.

## How the score is made

1. **The model** scores the payment: `p_lgbm`.
2. **The search** compares the payment's steps (the phone's `steps_seen` plus the server's own payee,
   payment and graph steps) with every playbook in `data/playbooks/playbooks.yaml` `search:`. The best
   match's `similarity` (0 to 1) is kept, with its matched and missing steps.
3. **Similarity to probability:** `p_playbook = isotonic(similarity)`, a curve learned on the
   calibration shards (`fusion.json` `playbook_iso`). No match gives 0. A weak match is worth little:
   a similarity of 0.32 maps to about 0.01, a perfect match to about 0.68.
4. **Fusion**, form `noisy_or` (the one in use):

   ```
   threat = 1 - (1 - p_lgbm) * (1 - p_playbook)
   ```

   Either strong source is enough; both strong is stronger. `fusion.py` also tries a logistic fit
   over `(logit p_lgbm, logit p_playbook, their product)` and keeps it only if its weighted log-loss
   is lower. On the current shards it was not (0.00239 vs 0.00238), so `form: noisy_or`.
5. **Floor:** the result is never below either part (`max(threat, p_lgbm, p_playbook)`), so a
   playbook match can only add to the model's evidence, never weaken it.

**Why the two stay independent.** The model never sees the similarity (it is not a training input),
and the search never sees the model's score. That is what makes "either strong is enough" honest
rather than counting the same evidence twice.

## From score to tier

`policy.yaml` `fused:` (rule 6: numbers in config, not in the artifact):

```yaml
fused:
  tiers: {T4: 0.4478, T3: 0.4478, T2: 0.1088, T1: 0.0121}
  t4_requires_intel_hit: true
  name_min_similarity: 0.6
```

- The policy walks T4 to T1 and takes the first bar the threat reaches. T4 also needs a registry or
  FRI hit (same as before), otherwise the payment stays T3.
- The bars are tuned by `python -m model.fusion` on the calibration shards: the lowest bars that keep
  honest payments at T1+ ≤ 20, T2+ ≤ 1.5 and T3+ ≤ 0.5 per 1,000. The script prints them; they are
  copied into `policy.yaml` by hand.
- **Naming the scam:** if the best playbook's similarity is at least `name_min_similarity`, it names
  the payment (`playbook`, `threat.fraud_type`) when the first-match matcher found none.

**Guardrails, applied after the tier, unchanged:**
- under ₹200 → at most T1 (`amount_caps`);
- "I know this person" → T0, unless a registry hit or screen control (`trusted_payee`);
- an analyst-approved playbook → at least T2 (`approved_playbooks`);
- the alert budget, which compares the fused threat (not `p_scam`) with `bypass_if_p_ge`, and never
  applies during a journey, when the payee family is lit, or to an anchor-then-drain attempt;
- fail open: any error or a slow answer is T0 with `fail_open` (rule 3).

## When there is no fusion

`threat.py` `load()` returns nothing, and the policy decides the old way (from lit families and
`p_scam`, the `tiers:` block with `corroboration_min_families: 2`), when:
- the scorer is the rules fallback (`rules-0.7`, e.g. LightGBM is not installed, or `--scorer rules`);
- `fusion.json` is missing or broken (logged as an error);
- `fusion.json` was fitted for a different model version (logged as a warning). A fusion file belongs
  to exactly one model: retrain the model, refit the fusion.

`GET /health` shows `"fusion": "lgbm-0.3+pg1"` when it is active, `null` when not.

## What the user and the analyst see

- **The app** (rule 4): `threat.level` in words (none / low / medium / high / critical, always
  following the tier), `threat.fraud_type` and the top reasons. Never the number.
- **The response** carries `threat.score = round(100 × threat)`; on fail open `threat` is `null`.
- **The analyst:** the evidence record and the transaction database (`decision_details.threat`) keep
  the parts: `{lgbm, playbook, similarity, best_playbook}`, plus the top three playbook matches with
  matched and missing steps (`playbook_search`). `policy_steps` contains `fused_threat` when the
  fused path decided.

## Numbers (calibration shards, `fusion.json` `calib`)

- 333,529 payments, 3,003 of them scams.
- A playbook matched 48% of scam payments and 5.6% of honest ones.
- Through the real policy: 92.4% of scam payments interrupted (98.6% of scam rupees), 1.23 honest
  interruptions per 1,000, T3 precision 85%.
- Honest interruptions by age band, per 1,000: 18–29 1.01, 30–44 1.27, 45–59 1.36, 60+ 1.82 (gap 1.8×;
  rule 14 audit only, age is never an input).
- Log-loss: the model alone is lower (0.0013) than the fused score (0.0024). The fusion is not there
  to calibrate better; it adds catches at the tier bars: on the sim_v2 test world, the model alone
  under the old gate interrupts 71% of scam payments, and the fused search adds about 20 points for
  0.4 honest interruptions per 1,000 (`docs/plan-v3.md`, Results).

Held-out test results (25 never-trained-on attack playbooks: 93.4% interrupted) are in
`docs/plan-v3.md`. They come from the same simulator as the training worlds, so real-world gains will
be smaller (`data/eval/realism/FINDINGS.md`).

## Refitting

```bash
PYTHONPATH=backend;ml;data python -m model.fusion --table ml/data/tables/v3/calib_*.parquet
```

Then copy the printed tier bars into `policy.yaml` `fused.tiers`. Do this after every retrain of the
server model (the file is checked against the model version) and after changing the playbook
search's steps or weights.

**Tests:** `backend/tests/test_fused_threat.py`:
- no match means the model alone;
- either strong part is enough;
- monotonic in both parts;
- the logistic form never counts less than either part;
- the file belongs to one model;
- tiers follow the threat without the two-families gate;
- T4 still needs an intel hit and the guardrails still apply;
- the alert budget reads the threat.
