# Security hardening (self red-team)

We ran a section-by-section red-team audit of the shield and fixed the structural evasions it found.
This is the record: what was wrong, what we changed, and what each teammate still needs to do.

The audit's headline was that an adaptive attacker could suppress three of the four evidence
families and slip most scam playbooks past the shield. The fixes below close the backend and config
holes; the biggest remaining one (the combiner's negative lure weight) is an ML retrain.

## Fixed (backend + config)

| # | Finding (audit §) | Fix | Commit |
|---|---|---|---|
| 1 | **Known-payee poisoning** (§2.1): a ₹100 "gate pass" set `paid_here=True`, so the drain to the same mule was no longer a new payee and the stage dropped. | A completed payment counts as "known" only when ≥ 48 h old and ≥ ₹500 (`policy.yaml known_payee`); a small recent payment is recorded as an anchor (`payee_micro_anchor`, family B) that raises R7. The bank's own history is unchanged. | `6a11bae` |
| 2 | **Salami slicing** (§2.5): many small QR/contact tranches, each below 1.5× the user's max, never lit behaviour. | 24 h cumulative outflow **to new/unknown payees** (any entry method) → `outflow_24h_to_max_90d` (family B), raises R7 past 1.5×. Established payees excluded, so legit instalments don't light it. | `27424cf` |
| 3a | **Corroboration gate vs a known mule** (§2.6): a human-verified mule alone still passed as T0. | A two-analyst-approved mule (rule 11) floors at T3 even as the only lit family (`approved_mule_min_tier`). Registry/FRI hits are deliberately **not** floored — a single crowd-sourced listing can be false, and the gate still guards that. | `1fa6b0b` |
| 3b | **Alert-budget exhaustion** (§2.6): trigger two minor T2s, then enjoy T1 downgrades. | The downgrade never applies during an anchor-then-drain pattern (`never_applies_with_anchor`). | `1fa6b0b` |
| 4 | **Call cool-off** (§2.2): a 4–14 min coaching call stayed under the 15 min long-call bar and vanished after 30 min. | `long_call_min` 15 → 5 (both `watch_rules.json` copies), so a 5-minute unknown call still reaches S2. | `411dfe0` |

New features (`payee_micro_anchor`, `outflow_24h_to_max_90d`) feed the **rule scorer now**; the
trained model will use them after a retrain (below). `ml/dataset/replay.py` mirrors the engine's new
known-payee logic so training rows match production (parity test green).

## Handed to teammates

### Diwansu (ml) — the biggest single fix
- **Non-negative combiner weights.** `server_model.json` learned `L = -0.3412` (and `C ≈ 0.030`), so
  raising a lure score *lowers* `p_scam`. Retrain the meta-combiner with non-negative weights
  (`LogisticRegression(positive=True)` or a bounded solver) in `ml/model/train.py`. (Audit §2.6.)
- **Retrain on the new features** so the model uses `payee_micro_anchor` and `outflow_24h_to_max_90d`
  (they already appear in replay rows).
- **Notification lures & call memory** (§2.2–2.3): `notification_lures_visible: true`, extend
  `call_memory_min`, and consider lowering `phone_view` + the app's `lure_send_threshold` to 0.40
  (needs the app's `LureScorer.LURE_SEND_THRESHOLD` and `contracts/watch_rules.json lure_min_conf`
  changed together — config-only change was skipped because the phone gates at 0.60 upstream).

### Nikunj (data) — so the red team actually exercises the fixes
- `data/sim_v2/agents/session.py` hardcodes `COACHED_CALL`/`CHAT` playbook-name sets, so a new
  playbook falls into calm "mixed" behaviour (§2.5). Drive the session profile from the scenario, not
  the name.
- Mule realism (§2.4): merchant-disguised cover payments, slow-forward holds, and mule-slot fan-out
  dilution let mules evade the payee features. Tighten the world so these are testable.

## Verify
- Backend + ML + Android unit tests are green with each fix (a test per change).
- **Miss-rate before/after:** run Nikunj's harness `python -m interface_script run-all` to measure
  the real drop. Not run yet — do it on request.
