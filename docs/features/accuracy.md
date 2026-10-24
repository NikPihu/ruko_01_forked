# Accuracy page: what RUKO gets right and wrong

**What it does.** The console's **Accuracy** page shows RUKO's results on data it never trained on,
with false alarms and misses next to the catches, and names its weak spots. It replaced the old
Evaluation page.

**Three held-out sources** (`backend/evalsuite/accuracy.py`):
1. **Payments:** the held-out simulated world `dev_test` (seed 12), replayed the way the phone and
   engine would have seen it (`ml/dataset/replay.py`) and decided through the real policy
   (`ml/model/evaluate.py`), for the live scorer and the rules. Shows:
   - a confusion table (scam or honest × interrupted or let through);
   - false alarms and gentle tips per 1,000 honest payments;
   - results per scam type;
   - the scams it missed, grouped, with what they had in common.
2. **Scam messages:** the phone's lure model on held-out message templates
   (`ml/model/artifacts/lure_metrics.json`), by language and message type.
3. **New scams:** the red team's 50 invented attacks (`red_team_blue_team/red_team/attack_manifest.csv`),
   the input the blue team learns from.

Then **named failure cases**, each with the number behind it (or "not measured"), why it happens and
what we do about it.

**Rebuild it** (minutes; after a retrain or a new red-team run):

```
PYTHONPATH=backend;ml;data python -m dataset.worlds dev_test
PYTHONPATH=backend;ml;data python -m dataset.replay --data ml/data/worlds/dev_test --out ml/data/tables/dev_test.parquet
PYTHONPATH=backend;ml;data python -m evalsuite.accuracy --table ml/data/tables/dev_test.parquet
```

It writes `backend/evalsuite/accuracy_results.json` (committed), served by `GET /v1/accuracy`.
Nothing on the page is computed live, and ground truth is read only to score (rule 9).

**Read with care:** the simulated world is too easy (`data/eval/realism/FINDINGS.md`), so payment
numbers mostly show that the pipeline works end to end; the red-team and message numbers are the
harder tests.

**Tests:** `backend/tests/test_accuracy.py`.
