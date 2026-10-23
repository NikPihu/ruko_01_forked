# Red team / blue team

RUKO's shield is tested the way a security team would test it:

- **Red team** (`red_team/`): invents and runs scams RUKO has never seen, including AI-powered ones
  (voice-clone relatives, chatbot "customer care", deepfake video KYC), to break the shield.
- **Blue team** (`blue_team/`): notices where the shield broke, works out what the new scam is,
  drafts a playbook for it and gets two human analysts to approve it, so RUKO names and warns
  about that scam from then on.

```
complaints (1930 / NCRP) ──► 1. breaches: payments RUKO let through (missed) or could not name (unnamed)
                              │
                              ▼
                         2. HDBSCAN over what the server saw per case ──► known scam that slipped? → tuning report
                              │ new cluster
                              ▼
                         3. investigator agent (Bedrock LLM + read-only tools) drafts a playbook card;
                            code validates it and backtests its matcher over every past payment
                              │
                              ▼
                         4. analyst agent (second LLM, skeptical): new scam / variant of a known one /
                            look-alike / not enough evidence
                              │
                              ▼
                         5. two human analysts approve ──► playbook database (approved/)
                                                           mule accounts → graph suspect review
                                                           labelled payments → next model retrain
```

No LLM decides anything about a payment (CLAUDE.md rule 13): the LLMs draft text and a matcher in
a fixed rule format, code tests it, people approve it, and an approved matcher only *names* the
scam. Tiers still come from the scorer and the two-family policy.

Run commands, results and what other folders need: [`blue_team/README.md`](blue_team/README.md).
