# Message check: scam script, looks AI-written, OTP warnings

**What it does.** Helps the user judge their own messages, on the phone. Nothing is sent to the
server. These labels are hints and never change a payment's tier (rules 2, 5, 10).

**Where the user sees it.**
1. **Message check screen.** Tap the "Message check" chip on Home. It lists the SMS from the last 3
   days, warnings first. Each card has labels:

   | Label | When |
   |---|---|
   | **Matches a scam script: fake KYC** (or arrest threat, refund, job, investment), red | the lure model (`lure.json`), confidence 0.6+ |
   | **Looks AI-written**, orange, with a short note that it is a hint, not proof | `ai_text.json` says so; only for personal numbers and chat messages with 12+ words, never business headers like `VM-HDFCBK` |
   | **OTP: never share this**, blue | any one-time code |
   | **No warning signs**, green | none of the above |

   An OTP that arrived during a call with someone not known to be a contact also gets the red line
   "Someone on a call asking for this code is a scammer".
2. **"This message may be a scam" notification.** It appears when a new SMS (or chat message, with
   "Check chat messages" on) matches a scam script. It says which kind, and adds "It also looks
   AI-written" when known. It never quotes the message. Tapping it opens Message check.
3. **"A code arrived while you are on a call" notification.** It appears when an OTP arrives during
   a call. This needs "SMS scam check" and "Call checks".

**How it works.**
- **The checks:** `signals/MessageCheck.kt` holds them:
  - `isOtp`, in English and Hindi;
  - `senderKind`: letters mean a business header, digits mean a person;
  - `duringUnknownCall`;
  - `check`.
- **Reading the phone:** `MessageScan` reads the SMS inbox and the call log.
- **Live checks:** `SmsReceiver` and `ChatListener` run the same checks on new messages.
- **The AI-written model** is Diwansu's `ai_text.json`, in the same format as `lure.json` (see
  `docs/ml-asks.md` §3). Until the file is in the app's assets, the label is unknown and hidden.
  AI-text detection is unreliable on short texts, which is why it says "looks", never "is".
- **Switch:** "SMS scam check" (off by default). It asks for permission to read and receive SMS,
  and to show notifications.

**Tests:** `MessageCheckTest.kt` covers:
- OTPs in English and Hindi;
- the warning during an unknown call (and none without one);
- bank headers never getting "AI-written";
- no label without a model or on short texts;
- scam script labels;
- the `ai_text.json` Python vectors, once that file exists.
