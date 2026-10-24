# How real fraud systems work inside, and how to mimic them in RUKO

## Context
- **Who and what:** The backend owns the risk engine for RUKO. Before the competition starts, it wants to understand how real Indian and global anti-fraud systems work inside, and how to copy or simulate each one in his experimental repo (`raksham_1`, only his part).
- **Scope:** no endpoints and no code yet. This note covers mechanisms, data, signals, blind spots, and how to mimic each one.
- **Inputs:** his PDF guide, `.claude/SPEC.md` and `.claude/CLAUDE.md` (from his earlier Claude chat), and web research.

**How sure each part is:**
- ✅ Publicly reported. Sources at the end.
- 🔶 Standard industry practice. True of how such systems are generally built, but no vendor publishes exact details.
- ❓ Inferred. The real internals aren't public, so this is a reasonable guess to mimic.

---

## 1. First, how a UPI payment actually flows (where checks can happen)

```
Payer app (PSP, e.g. PhonePe) ──▶ Payer's PSP bank ──▶ NPCI UPI switch ──▶ Remitter bank (debits payer)
                                                                         ──▶ Beneficiary bank (credits payee)
```

1. **Payee entered.** The app resolves the VPA and shows the registered name. This is India's informal "confirmation of payee".
2. **Pay tapped.** The app builds the request. This is the window **RUKO targets**: after Pay, before the PIN. Phone context only exists here.
3. **PIN entered.** The request goes to the switch. Banks and NPCI run their **FRM** (fraud risk management) checks here in milliseconds.
4. **Money lands in seconds.** After that, recovery depends on the victim reporting and a **lien** (hold) on the mule account. That is the 1930 / CFCFRMS path.

**Key insight for the pitch:** each existing system sees only one slice of the scam:
- The bank sees the transaction.
- The telco (DoT/FRI) sees the phone number.
- RBI's MuleHunter sees the receiving account.
- The police (I4C) see reports after the loss.

Nobody combines **phone context at the moment of payment** with **payee risk**. That gap is RUKO's whole reason to exist.

---

## 2. The real systems, one by one

### 2.1 Bank / NPCI transaction FRM: the "existing stack"
**How it works inside** 🔶
- **Two layers:**
  1. A **rules engine** with hard limits and velocity rules, for example "more than 5 payments in 10 minutes", "new payee and amount over ₹50k", "device changed in the last 24 h".
  2. An **ML score** from gradient-boosted trees, trained on past fraud labels.
- **Customer profiles:** running statistics kept per customer in a fast store:
  - mean and median amount
  - largest payment in 90 days
  - usual hours
  - usual payees
  - device ids
- **Velocity counters:** counts and sums over sliding windows (1 h, 24 h, 7 d), kept per customer, per device and per payee.
- **Output:** a score, which thresholds map to actions:
  - allow
  - step-up (OTP or warning)
  - hold for review
  - decline
- **Case management:** an analyst queue. Analyst decisions become **labels** that retrain the model.
- **Champion/challenger:** a new model runs in shadow next to the current one before it replaces it.

**Blind spot for APP scams:** the victim's own device, PIN and behaviour all look legitimate. A large payment to a new payee also looks like buying a bike or paying a hospital, so either alerts flood or the scam gets through.

**Mimic in RUKO**
- This is the **baseline** ML trains: transaction-only features such as amount ratio, new payee, hour and velocity.
- RUKO's claim is to beat it **at the same alert budget**.
- From this layer you take two ideas:
  - **per-user baselines in Redis**, which is the "feature store"
  - **sliding-window counters**, used for tranches and payee fan-in

### 2.2 DoT Financial Fraud Risk Indicator (FRI): phone-number risk
**What is public** ✅
- Launched in May 2025 by DoT's **Digital Intelligence Platform (DIP)**.
- Classifies a **mobile number** as Medium, High or Very High risk of financial fraud.
- Inputs:
  - I4C's National Cybercrime Reporting Portal (NCRP)
  - DoT's **Chakshu** reports (citizens reporting suspicious calls and SMS)
  - intelligence shared by banks
- RBI advised all banks to integrate it on 30 June 2025, via API.
- **PhonePe declines** payments linked to Very High numbers and planned warnings for Medium.

**How it likely works inside** ❓
- Each number collects evidence events: complaints, Chakshu reports, bank flags, and possibly disconnection by DoT.
- The events are weighted by source reliability and recency.
- The weighted total is bucketed into the three levels.
- The result is published to subscribers.

**Blind spots to reproduce:**
- **Lag:** a number only becomes risky *after* victims report, often days later.
- **Coverage:** scammers rotate SIMs and use VoIP and WhatsApp calls from foreign numbers, so a fresh number has no rating.
- **Keyed on the mobile number,** not on the UPI ID or account.

**Mimic in RUKO**
- Generate reports from the simulator's ground truth: each victim reports with probability of about 0.5, after 1–7 days.
- Score per number = Σ (weight × recency decay), bucketed into NONE, MEDIUM, HIGH and VERY_HIGH.
- Add about 1% false entries.
- VERY_HIGH is a **hard rule** that sets a minimum tier and counts toward T4. MEDIUM is just a feature.
- It belongs to the **P/intel family**, not a separate family. Three government lists still count as one family.

### 2.3 I4C Suspect Registry: the identifier blacklist
**Public** ✅
- Run by I4C (Ministry of Home Affairs).
- A registry of identifiers reported in cybercrime: bank accounts, UPI IDs, phone numbers.
- Shared with banks.

**Likely internals** ❓
- An identifier is added when it appears in confirmed NCRP or 1930 complaints.
- Each entry carries a reported date and a count.

**Blind spots:**
- Only reported scams get in. The SPEC's report rate of about 49% is a modelling assumption.
- Reporting lags by days.
- Fresh mule accounts are not listed.
- Honest accounts can be **falsely listed** through mass false reports, which is one of the red-team tests.

**Mimic in RUKO**
- A set of `payee_hash → {reported_on}` entries, filled from simulated victim reports with a lag.
- Rule: a registry hit alone may raise the tier minimum, but never blocks a payment without corroboration. This defends against false reports.

### 2.4 RBI MuleHunter.AI: receiving-account risk
**Public** ✅
- Built by the RBI Innovation Hub (RBIH).
- An in-house AI/ML model that flags likely **mule accounts**.
- RBIH studied **19 distinct mule-behaviour patterns** with partner banks.
- RBI says rule-based mule detection gives high false positives and slow turnaround.
- Adoption: started with 2 public-sector banks, live in **29 banks by July 2026**.

**How it likely works inside** 🔶❓
- An **account-level** classifier, likely gradient boosting, trained on each bank's confirmed mule labels.
- It runs as a **periodic batch** over the bank's own accounts, and the bank acts on the scores (freeze, step-up KYC).
- Typical mule features:
  - **fan-in:** many unrelated payers
  - payers spread across regions
  - **pass-through:** money out shortly after money in
  - short median hold time
  - young account or recent KYC
  - dormant account suddenly active
  - low repeat-payer ratio
  - round amounts
  - outflow to other young accounts
  - shared devices or IPs across accounts

**Blind spots:**
- Each bank only sees **its own** accounts.
- Scores are **batch**, so a mule opened yesterday may be unscored.
- Disguised mules (fake merchants, slow forwarders, warmed-up accounts) are harder to catch.

**Mimic in RUKO**
- Train a small model on the simulator's accounts, labelled `is_mule`.
- Return scores **only for "partner" banks**, recomputed **once per simulated day**, and `null` for anything newer.
- This produces the "fresh mule" gap that RUKO's live payee graph fills.

### 2.5 RUKO's own live payee graph: your real advantage over MuleHunter
This mimics what **Mastercard Consumer Fraud Risk** and network-level systems do. It runs **live** from the transaction stream instead of in daily batches.

**Mastercard CFR** ✅
- Scores any UK bank transfer for the risk that the **payee** is a scam account.
- Score from 0 to 999, returned in under half a second, before the money leaves.
- Uses account names, payment values, payer and payee history, and the payee's links to known mule accounts.
- Built from years of tracing mule money with UK banks.
- Mastercard says 11 UK banks use it. TSB reported a **20% increase** in detection; this figure comes from the vendor.

**Mimic in RUKO (data structures):**
- **Unique payers in 6 h:** a Redis **sorted set** per payee with the payer as member and the timestamp as score. Trim old entries, then count.
- **Pass-through:** rolling inflow and outflow sums per payee, with ratio = out ÷ in over 24 h.
  - Median hold time = time between a credit and the matching debit.
- **Repeat-payer ratio:** a set of all past payers.
  - Kirana shops score **high**: the same neighbours pay every day.
  - Mules score **low**: strangers pay once.
  - This one feature separates the main hard negative (the busy shop) from a mule.
- **Account age, region spread, outflow to young accounts.**
- **Graph idea (stretch):** mules forward money to other mules.
  - One hop of "money went to a known mule", or a simple label propagation over the payment graph, catches rings that single-account features miss.
- **Mule pump for the demo:** before the demo, send about 40 small payments from random payers into the demo mule, and forward about 90% out within minutes. The live graph then lights R3 even though MuleHunter and the registry know nothing.

### 2.6 BioCatch-style behavioural signals: context and behaviour
**Public** ✅
- BioCatch's Scams360 (July 2025) flags APP scams from in-session behaviour:
  - an **active phone call during the transaction**
  - **remote access or screen sharing**: it tells passive sharing from active control by guided navigation, copy-paste, resolution changes and expert shortcuts
  - **hesitation / dead time**
  - unusually long time to complete the payment
  - erratic typing
- Signals are assessed **together**, not one at a time.

**Mimic in RUKO**
- The phone SDK (android/) sends *derived flags only*. These map to RUKO's families:

| Family | Flags |
|---|---|
| C | on a call or call ended recently ("call memory", about 30 minutes); caller unknown or not in contacts; VoIP call from a number, possibly foreign |
| C | remote-access app recently installed (AnyDesk, TeamViewer QuickSupport, RustDesk, AirDroid); untrusted accessibility service; sideloaded APK |
| B | time spent on the amount screen; number of amount edits; UPI ID typed by hand |

- Your engine turns these into features plus **stage transitions**.

### 2.7 UK Confirmation of Payee and India's name display
**Inside** ✅🔶
- Before the payment, the sending bank asks the receiving bank whether the name matches the account.
- It answers with a match, a close match or no match.
- UPI already shows the registered name.

**Mimic in RUKO** (an idea from SPEC.md)
- Ask "**Who are you paying?**" for first-time payees over about ₹5,000. Answers: government/police/RBI, company, family, shop.
- **Name/story mismatch** = the user says "government" but the payee is a *personal* account.
- No real government body takes UPI payments to a personal account, so this is a strong digital-arrest signal.

### 2.8 1930 helpline / CFCFRMS: recovery after the loss
**Public** ✅
- Run by I4C as an integrated platform linking police, banks and payment firms.
- When a complaint is registered, an **automated money trail** follows the money from account to account and puts a **lien** (hold) on as much of the disputed amount as it can trace.
- Critics note the lien step has little human review, so honest accounts can get frozen.
- The "golden hour" idea is that early reporting recovers more, because money is forwarded within minutes. That timing isn't confirmed in the sources found.

**Mimic in RUKO**
- The **evidence vault** produces a tamper-evident record (hash chain) with:
  - time
  - reasons
  - stage path
  - payee hash
  - which intel was available at that moment
- The user or analyst can attach it to a 1930 or NCRP report.
- Feedback such as `called_1930` and `was_scammed` becomes training labels. This mirrors how real FRM learns from confirmed fraud.

### 2.9 Platform-level shared intelligence: DPIP
- ✅ RBI's **Digital Payments Intelligence Platform**: shared risk data across banks to flag unusual payments. A pilot with 7 banks; the Finance Ministry is pushing for rollout.
- **Mimic:** out of scope. Use it in the pitch: "In production, RUKO's payee features come from DPIP, so every bank sees every payee."
- SPEC.md models this as **visibility levels**:
  - L0: any app
  - L1: the payee's PSP
  - L3: the payee's bank
  - L4: network / DPIP
- Train with features blanked by level, so the model works even when payee data is partial.

---

## 3. Cross-cutting techniques real systems use, and your version of each

| Real-world technique | What it is | Your version |
|---|---|---|
| **Customer profiling** | Running statistics per customer | User baselines in Redis: largest payment in 90 days, median, usual payees |
| **Sliding-window velocity** | Counts and sums over time windows | Sorted sets with trimming; tranche sum over 72 h |
| **Rules + ML hybrid** | Hard rules set minimums; ML ranks the rest | Intel hits as hard rules, LightGBM for p_scam, YAML policy on top |
| **Calibration** | Turning a model score into a true probability, so thresholds mean something | ML's isotonic calibration. A threshold like p ≥ 0.75 is only meaningful if calibrated. |
| **Reason codes** | Regulators and users need *why*, not a number | SHAP top contributors mapped to R1–R8, shown as plain words. Never show the score. |
| **Step-up friction tiers** | Escalating response instead of block/allow | T0 nothing, T1 tip, T2 explain card, T3 pause plus trusted contact, T4 analyst hold |
| **Alert budget / fatigue control** | Limiting how often a user is interrupted | At most 2 interruptive alerts per 30 days unless p ≥ 0.9 |
| **Corroboration** | Several independent sources must agree | At least 2 lit *families*. The three government lists count as one family. |
| **Allowlists** | Trusted payees and merchants | "I know this person" is suppressed, unless there is an intel hit. SPEC.md also suggests stage ≥ S3, since coached victims tap it. |
| **Label delay and feedback** | Fraud labels arrive days later | Simulated report lag; feedback endpoint updates labels |
| **Fail-open SLA** | Fraud checks can't break payments | 200 ms budget, then T0 |
| **Audit trail** | Regulators require explainable, unaltered records | SHA-256 hash chain plus a verify step |
| **Champion/challenger and ablation** | Prove each signal earns its place | the evaluation: drop one family at a time; compare with and without RUKO at the same alert budget |

---

## 4. The one rule that makes your mocks credible
Real systems have **coverage gaps, lag and false entries**. If the mock FRI, registry or MuleHunter "know" the ground truth, the existing stack looks perfect, and RUKO's improvement becomes either fake or invisible.

So every mock must:
- see only reported or eligible items
- appear only after a delay
- cover only some banks
- contain a few wrong entries

The judges' first question will be "why doesn't MuleHunter or FRI already catch this?" Your answer is the **fresh mule plus live call context** that those systems structurally can't see in time.

---

## 5. What to do with this before the competition (no code yet)
1. Read the competition rules on how much pre-written code is allowed.
2. With data/, agree how the simulator produces the blind spots: report rate, report lag, partner-bank coverage, false entries, mule types.
3. With ML, agree the two models (transaction-only baseline vs RUKO), the family thresholds, and the feature list.
4. At P1, settle the PDF-vs-SPEC differences:

| Topic | PDF guide | SPEC.md |
|---|---|---|
| Endpoints | `/v1/decide` | `/prefetch` + `/score` |
| Reason codes | 8 codes | 14 codes |
| Amount cap | Under ₹200 | Under ₹500 |
| Intel timeout | 150 ms | 50 ms |
| Device trust | Mock attestation | EC signing |
| Mock UPI network and cross-app pause | Absent | Present |
| Time format | ISO 8601 +05:30 | UTC epoch |
| Payee id | Hashed | Raw VPA |
5. Prepare short Q&A answers:
   - Where does RUKO plug in? Between Pay and the PIN screen.
   - What if RUKO is down? It fails open.
   - Why don't FRI or MuleHunter already catch this? Lag and coverage.
   - How are records proven unchanged? The hash chain.
   - How is privacy kept? Only derived flags leave the phone, and ids are hashed.

## Verification of this note
- ✅ facts come from the sources below.
- 🔶 and ❓ items are modelling choices, not claims about the real systems. Say so in the pitch ("modelled on publicly described behaviour").

## Sources
- [DoT FRI launch — Business Standard](https://www.business-standard.com/industry/news/dot-launches-financial-fraud-risk-indicator-to-aid-cybercrime-detection-125052101912_1.html)
- [RBI advises banks to use FRI — Morung Express](https://morungexpress.com/rbi-advises-banks-to-use-dots-financial-fraud-risk-indicator-to-prevent-cyber-swindling)
- [How FRI empowers stakeholders — Governance Now](https://www.governancenow.com/news/regular-story/how-dots-fraud-risk-indicator-empowers-stakeholders)
- [MuleHunter.AI explainer — Outlook Business](https://www.outlookbusiness.com/economy-and-policy/rbi-introduces-ai-to-curb-financial-frauds-how-mulehunter-ai-will-tackle-mule-accounts)
- [MuleHunter.AI, 19 patterns — Vajiram & Ravi](https://vajiramandravi.com/current-affairs/rbi-launches-ai-powered-model-mulehunter-ai/)
- [FinMin asks banks to use MuleHunter — Outlook Business](https://www.outlookbusiness.com/economy-and-policy/finance-ministry-asks-banks-to-use-mulehunterai-to-check-digital-fraud)
- [DPIP rollout push — Business Standard](https://www.business-standard.com/finance/news/fin-min-pushes-rbi-to-expedite-launch-of-platform-to-curb-digital-frauds-125093000979_1.html)
- [Mastercard real-time payment scams press release](https://www.mastercard.com/news/press/2023/july/mastercard-leverages-its-ai-capabilities-to-fight-real-time-payment-scams/)
- [Nine British banks sign up — American Banker](https://americanbanker.com/payments/articles/nine-british-banks-sign-up-to-new-ai-tool-for-tackling-scams)
- [BioCatch Scams360 press release](https://www.biocatch.com/press-release/biocatch-delivers-scams360)
- [BioCatch remote access attacks](https://www.biocatch.com/use-case/customer-protection/remote-access-attacks)
- [CFCFRMS account-freeze SOP — LiveLaw](https://www.livelaw.in/articles/cfcfrms-reading-mha-new-account-freeze-sop-537503)
- [Mule detection signals (vendor) — Feedzai](https://feedzai.com/wp-content/uploads/2024/11/Feedzai-Inbound-Payment-Fraud-Detection-and-Mule-Risk-Modeling-Complying-with-Bank-Negara-Malaysia-Recommendations.pdf)
