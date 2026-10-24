# Ruko Shield — 50 Red-Team Breakthrough Scam Playbooks (`sim_v2` Format)

All 50 YAML playbooks in `playbooks/` follow the exact `data/sim_v2/config/playbooks/*.yaml` state-machine contract and were evaluated against the local Ruko Shield stack (`sim_v2` 300 users x 14 days background world, 20 compliant victims per playbook, `PhoneView` + `EpisodeFeed` + `device-0.1` on-device verdict + `lgbm-0.2` server LightGBM scorer + `rules-0.7` fallback scorer + `policy.yaml`).

## Breakthrough Summary
- **Total Playbooks**: 50
- **LightGBM (`lgbm-0.2`) Breakthroughs**: **50 / 50 (100%)** (`missed_share >= 0.75` where `threat_score <= 70`)
- **Rule Scorer (`rules-0.7`) Breakthroughs**: **50 / 50 (100%)**
- **Average LightGBM Miss Rate Across All 50 Playbooks**: **97.5%** (average threat score: **3.8 / 100**)
- **Average Rule Scorer Miss Rate Across All 50 Playbooks**: **97.5%** (average threat score: **20.3 / 100**)

## Adversarial Evasion Vectors Exploited
1. **Call-Memory Cool-Off (`gap_min > 30` min, no `during_call: true`)**: Coaching the victim on an incoming/outgoing call and instructing them to pay via QR/contact 40–150 minutes after hanging up (`ContextSensor.CALL_MEMORY_MS = 30 min`), zeroing out Family C (`on_call=False`) and relaxing `pay_session` typing dynamics.
2. **Notification-Only Lure Delivery (`notification_lure`)**: Delivering hooks via WhatsApp, Telegram, or Instagram notifications (`notification_lures_visible: false` in `phone_view.py`), keeping `lure_max_conf_72h = 0.0` in Family L.
3. **Sub-Threshold SMS Lures (`conf < 0.60`)**: Crafting polite/Hinglish utility, parcel, and subsidy SMS lures whose classifier confidence stays below `lure_send_threshold = 0.60` and `watch_rules.json` (`lure_min_conf = 0.75`).
4. **Task-Scam Episode Watcher Evasion (`episode_state <= 1`)**: Keeping `crew_pays` bait credits to `repeat: 1` (below `min_bait_credits: 2`), or sending stipends above `bait_max_inr: 500`, or keeping step escalation `< 1.5x` (`escalation_factor: 1.5`) to prevent `episode_state` from reaching `2 (active)`.
5. **Known-Payee Poisoning (`paid_here = True` via Small Anchor)**: Requesting a tiny ₹100–₹250 verification/gate-pass payment to the mule first (`amount_cap_500` caps tier at `T1`), which records a completed payment in `GraphStore` (`paid_before() = True`). Subsequent ₹1,200–₹4,200 payments to the same mule (`mule: same`) see `first_time_payee = False`, `attempts_72h = 0`, and remain in stage `S1`/`S2` instead of `S4`/`S5`.
6. **Non-Typed Entry (`qr` / `contact`)**: Avoiding `entry: typed` suppresses `R6_new_payee_typed`, skips the `"Who are you paying?"` prompt (`ask_from_inr: 2000` for typed only, eliminating `story_mismatch`), and prevents `payee_pasted` session flags.
7. **High-Slot Merchant-Disguised & Rented Mules (`mules.slots: 8-10`, `merchant_disguised` / `rented` / `slow_forward`)**: Diluting per-mule fan-in (`uniq_payers_6h`, `uniq_payers_7d`) and injecting merchant cover payments (`mule_cover`) so `repeat_payer_ratio_30d` stays high and `payee_mulehunter` stays low.

## Usage with Plan v3 Red-Team Runner
```bash
# Run a single breakthrough playbook
python -m redteam run --playbook playbooks/courier_customs_cooloff.yaml --victims 20 --server local

# Run all 50 breakthrough playbooks
python -m redteam run-all --playbooks playbooks/ --server local
```
