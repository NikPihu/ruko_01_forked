# Playbooks file: the scam types the engine names

**What it does.** Names what a risky payment looks like (digital arrest, fake KYC app, refund QR,
fake customer care, trading group, task job). The scam type picks the app's message
(`<tier>_<playbook>`) and is shown to the user in words.

**Where.** `data/playbooks/playbooks.yaml`. The data folder owns the list; the format and loader are
in `backend/api/playbooks.py`. This is not the same as the simulator's journey scripts in
`data/sim_v2/config/playbooks/`, which describe how a scam runs step by step.

**Format.** Entries are checked top to bottom; the first one that matches names the payment.

```yaml
version: playbooks-0.1
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
- **Visible:** `GET /health` says which one is in use: `"playbooks": "file:playbooks-0.1"` or
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
