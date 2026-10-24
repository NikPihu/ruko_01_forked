# Playbooks file: the scam types the engine names

**What it does.** Names what a risky payment looks like (digital arrest, fake KYC app, refund QR,
fake customer care, trading group, task job). The scam type picks the app's message
(`<tier>_<playbook>`) and is shown to the user in words.

**Where.** `data/playbooks/playbooks.yaml`. The data folder owns the list; the format and loader are
in `backend/api/playbooks.py`. This is not the same as the simulator's journey scripts in
`data/sim_v2/config/playbooks/`, which describe how a scam runs step by step.

**Format.** Entries are checked top to bottom; the first one that matches names the payment.

```yaml
version: playbooks-0.3
playbooks:
  - name: refund_qr
    why: "an unknown caller on the line + a payee that was not typed (QR or picked)"
    match: {on_call: true, unknown_caller: true, entry_typed: false}
```

How conditions are read:
- Names are `features/build.py` features, plus `unknown_caller` (not a contact, or an unseen VoIP
  number).
- `true`: the feature is set.
- `false`: it is not set, or it is unknown.
- Any other value: must be equal.
- A list: must be one of them.
- `any: [...]`: at least one of the condition maps must hold.

**Safety.**
- **Strict file:** a misspelled feature, an empty `match` or an unknown key makes the whole file
  count as wrong.
- **Fallback:** the engine then logs it and uses the same rules built into the code (`BUILTIN`), so
  payments are never left unchecked.
- **Visible:** `GET /health` says which one is in use: `"playbooks": "file:playbooks-0.3"` or
  `"builtin"`.

**Adding a scam type.**
1. Add an entry in the right place in the list.
2. Restart the API.
3. Optionally, add app words for `t2_<name>` / `t3_<name>` / `t4_<name>` in `AlertText.kt` and the
   strings files. Until then the app shows the tier's general text.

Naming a pattern on the console's **Emerging patterns** page drafts an entry in this format
([emerging-patterns.md](emerging-patterns.md)).

**Tests:** `backend/tests/test_playbooks.py`. It checks:
- the file and the built-in rules agree on 5,000 made-up payments;
- every entry can match;
- bad files are refused;
- a new entry works without code;
- an emerging-pattern draft loads.

## Playbook search (playbooks-0.3, plan v3 step 3)

The `playbooks:` list above *names* a payment (first match wins). The `search:` section next to it
says **how much** a payment's journey looks like each known scam, from the scam steps of
`contracts/steps.json`.

- **Format:** each scam is a list of items: one `step`, or `any` of several, with a `weight`; some
  are `required`. Example: digital arrest needs an unknown call (or an arrest-threat message) *and*
  screen control, a video call, dictated typing or an arrest threat; a long call, a large amount, a
  new payee and a mule-like payee add to it.
- **Score** (`backend/api/playbook_search.py`): every required item must be seen; a required item
  measured and not seen rules the scam out (`blocked_by`), one not measured leaves no match (an
  unknown is no evidence either way, rule 1). Then similarity = seen weight / (measured weight + half
  the unmeasured optional weight). Weights are multiplied by how rare a step is across the
  playbooks, so a new payee (every scam) counts less than a video call.
- **Steps of a payment:** the server's reading (`features/steps.py server_steps`, from the engine
  features and the request) merged with the phone's (`device_verdict.steps_seen`, c2-0.14): seen if
  either saw it, not seen if one measured it, else unknown.
- **Where it shows:** the transaction database (`decision_details.steps`, `.playbook_search`: the top 3
  with matched, missing and unmeasured steps), the evidence record (`family_scores.playbook_search`)
  and `GET /health` (`playbook_search`). **It does not change the tier yet**; plan v3 step 5 fuses it
  with the model score.
- **Offline:** `python -m model.search_eval --table <replay tables>` (ml) writes
  `ml/model/artifacts/search_eval.json`. On the held-out tables (`dev_test_v3`, `rt_test_v3`): the
  known scams are found on 74-100% of their payments in the known-scam world (trading_group 17%:
  that world shows no trading message within 72 h of the payment), with the right scam on top for
  56-87%; 4-6% of honest payments match something, 11-16 per 1,000 at similarity 0.7 or more (people
  who got a scam message and did not pay a scammer). The attack playbooks the search has never seen
  match 30% of their payments.
- **A broken `search:` section** turns the search off (`"playbook_search": "none"`), never the engine.

**Tests:** `backend/tests/test_playbook_search.py`, `test_store.py` (the engine records it),
`ml/tests/test_steps_table.py`.
