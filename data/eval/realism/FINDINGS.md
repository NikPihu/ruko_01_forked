# RUKO data analysis: team simulator vs old prototype vs real data

Date: 2026-10-21. Reproduce from the repo root (writes `data/eval/realism/results.json`):

```bash
PYTHONPATH=backend:ml:data python -m sim.generate --users 2000 --days 30 --seed 7 --out data/
PYTHONPATH=backend:ml:data python -m eval.realism.compare --team data/ [--old-sim path/to/old/ruko]
```

| Dataset | What it is | Size used |
|---|---|---|
| **Team sim** | `ruko_01/data/sim` (current main), `--users 2000 --days 30 --seed 7`, the repo's default | 63,958 user payments, 23 journeys, 77 scam payments |
| **Old sim** | the Oct-17 prototype `ruko_sim` (4,000 users × 60 days) | 344,469 payments, 240 journeys, 487 scam payments |
| **PaySim** | Public synthetic mobile money (Kaggle) | 6.36 M rows |
| **Xente** | Real e-payments, Uganda, Nov 2018–Mar 2019 | 95,662 rows |

"Single-feature AUC" means ROC AUC from one raw column with no model. Anything above about 0.95 means the label leaks through that column.

## Headline: the team data is too easy, and has too few positives

| Metric | Team sim | Old sim | PaySim | Xente (real) |
|---|---|---|---|---|
| Fraud rate (per payment) | 0.12% | 0.14% | 0.13% | 0.20% |
| Scam journeys | **23** (3 are demo) | 240 | n/a | n/a |
| Scam payments | **77** | 487 | 8,213 | ~190 |
| Fraud median / legit median | 87× (P2P only: 13×) | 78× | 5.9× | 650× |
| Fraud share above legit p90 | 95% | 93% | 54% | 99% |
| Best single-feature AUC | **0.994** (`payee_age_days`) | 0.979 (amount ratio) | — | — |
| P2M share of user payments | **87.5%** | 61% | — | — |
| Share of legit payments at 1–5 AM | **4.4%** | 1.1% | 0.6% | 1.7% |
| Payments per user (30 d), std / mean | **4.7 / 32** | — | — | heavy tailed |

## Problems found in the team simulator, by severity

### 1. Mule accounts are given away by account age (label leak)
- Every normal account is **≥ 396 days old**. Every mule is **≤ 62 days old** (median 41).
- A single cut at about 100 days separates them perfectly. That's why `payee_age_days` alone scores AUC 0.994 and `payee_is_mule` scores 0.993.
- Even the `warm_up` and `merchant_disguised` mule kinds stay under 60 days.
- Real mule networks also rent aged accounts (the old sim had `mule_aged` / `mule_rented`). Normal users also open new accounts, and new merchants and QR stickers appear all the time.
- **Fix:** give normal accounts a realistic age mix with plenty of new ones, and add aged and rented mules. Then any model has to rely on behaviour (inflow fan-in, fast forwarding) rather than age.

### 2. Too few positives to train or evaluate anything
- 23 journeys and 77 scam payments over 30 days. Take away the 3 demo journeys and some playbooks have only **2 journeys** (task_job, fake_kyc_apk, refund_qr).
- A held-out test set would have about 15 scam payments, so any recall or precision number has a confidence interval of ±20 points or worse.
- **Fix:** keep `scam_rate` realistic for the precision estimate, but generate a separate training world with a much higher victim rate (the old sim used 6%). Or scale up to 4,000 users × 60 days. Report precision by reweighting to real prevalence.

### 3. Context signals that appear only in scams (label leak)
- `notification_lure`, `remote_session_notice` and `accessibility_enabled` occur **only** in scam journeys (18 / 8 / 2 events, all labelled scam), so any model gets a free rule.
- Meanwhile `sms_lure` fires 1,842 times on non-scam users and only 5 times in scams. The lure signal is mostly noise, and most scam journeys (18 of 23) get no lure at all.
- Only 16 scam calls exist for 23 journeys, so many digital-arrest and customer-care journeys have no call. The core "on a call while paying" signal is missing.
- **Fix:** add hard negatives for every scam-only signal: real AnyDesk or TeamViewer use by IT and support staff, accessibility apps for elderly users, banking-app notifications. Make every playbook that starts with a call actually emit the call, overlapping the payment.

### 4. Amounts make scams trivially obvious
- Scam payments are 87× the legit median (13× within P2P). `log_amount` alone scores AUC 0.98, and 95% of scam payments sit above the legit p90.
- Minimum scam payment is ₹500, median ₹17,500, and 71 of 77 are typed.
- Real task-job and trading scams start with small "trust" payments (₹100–₹1,000) and escalate. PaySim's fraud is only 5.9× the legit median, with 54% above p90.
- **Fix:** add the escalation ladder (small payments first). Allow some scam payments by QR or contact. Add large legit P2P payments as hard negatives (rent, family transfers, school fees, gold). The old sim had 10 hard-negative patterns and 24k hard-negative payments; the team sim has very few.

### 5. Normal-life behaviour is too uniform and not realistic enough
- **Users all behave the same.** Payments per user over 30 days have mean 32 and std 4.7 (min 17, max 48), which is roughly Poisson. Real users are heavy tailed: some pay twice a month, some 10 times a day.
- **P2M share is 87.5%.** NPCI volume splits are closer to 60/40 P2M/P2P, which matches the old sim's 61%. With so few P2P payments, every P2P payment looks a little suspicious.
- **Too much night activity.** 4.4% of legit payments happen 1–5 AM, against 1.7% in Xente and 0.6% in PaySim. The team's hour curve has a flat floor of about 0.7% per hour all night. Scam payments spike at 16:00 (21% of all scam payments in one hour).
- **Fix:** add per-persona activity rates (log-normal), a real night-time dip, and a P2M share calibrated to NPCI. Spread scam timing by playbook (digital arrest during working hours, task job in the evenings).

### 6. Small bugs
- `python -m sim.generate` crashes on Windows at the final `print(summary(...))`, because the console code page can't print `₹` (UnicodeEncodeError). The Parquet files are written before the crash, so the data is fine. Fix: `sys.stdout.reconfigure(encoding="utf-8")` or print `Rs`.
- The README tells you to run `export PYTHONPATH=backend:ml:data`, but on Windows the separator is `;`.

## What the team sim already does well (keep it)
- Account-level ledger with realistic flows: mule forwarding, cover traffic, cashbacks, repayments, gig payouts.
- NPCI-style handle and bank routing, and report and listing lags for the mock intel services.
- Fairness columns (age_band, language) kept separate as audit-only.
- Its legit hour curve is the right overall shape (L1 distance to Xente is 0.21; PaySim vs Xente is 0.31). The problem is only the night floor.

## Suggested build order for the new data side
1. Fix the mule age leak and add aged and rented mules (§1).
2. Add hard negatives for every scam-only signal and large legit payments (§3, §4).
3. Split into a training world (high victim rate) and an evaluation world (realistic prevalence), and scale up (§2).
4. Calibrate normal life: heterogeneous users, P2M share, night dip (§5).
5. Add an automated realism check: re-run `compare.py` in CI and fail if any single raw feature has AUC above 0.95.
