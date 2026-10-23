# Emerging patterns: scam workflows nobody has named yet

**Why.** The problem statement is "detect emerging AI-enabled scam workflows". Known scams have
playbooks; a new one does not. This finds groups of risky payments that happen the same way but
match no playbook, so an analyst can name the new workflow.

**How it works** (`backend/patterns/emerging.py`; offline and analyst-only, never part of a
payment's decision, rule 13):
1. **Take recent payments.** From the transaction database, take the last 7 days of flagged (T1+)
   and near-miss (T0 with one lit family) payments that matched **no** playbook.
2. **Give each a signature in plain signals:**
   - the call (video, VoIP, unknown caller, the user calling an unknown number);
   - the scam message type;
   - screen control or a sideloaded app;
   - Pay-screen signs (dictated amount, UPI ID pasted after switching apps);
   - entry method;
   - new payee;
   - an amount band;
   - the lit families.
3. **Group payments with the same signature.** A group with 5+ payments from 3+ different people
   is listed, with whether it is growing. The numbers are in `policy.yaml` `emerging:`.
4. **Describe it in words**, e.g. "12 payments from 9 people since 20 Oct: video call from an
   unknown caller → screen control → a new payee, ₹20k–50k. Matches no known scam type."

**Console: Emerging patterns page.** Each group shows example payments, first and last seen, and
growth. An analyst can:
- **Name it.** This returns a draft entry for `data/playbooks/playbooks.yaml` in the loader's
  format ([playbooks.md](playbooks.md)), for the data owner to check and add.
- **Dismiss it.**

Every action is recorded (`pattern_reviews`), and nothing here changes a payment's tier.

**Proof.** The demo agents include a hidden scam type with no playbook (a fake "your son is in
hospital" call, with the UPI ID pasted from a message). After one run it is listed here, while the
known scam types are not.

**API:** `GET /v1/patterns/emerging`, `POST /v1/patterns/{id}/review`.
**Tests:** `backend/tests/test_emerging.py`; `test_playbooks.py` checks the draft loads.
