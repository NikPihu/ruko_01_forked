package com.ruko.demo.shield

import com.ruko.demo.signals.AiTextScorer
import com.ruko.demo.signals.BankSms
import com.ruko.demo.signals.LureClassifier
import com.ruko.demo.signals.MessageCheck
import com.ruko.demo.signals.MessageLabel
import com.ruko.demo.signals.MoneyTxn

/** What one incoming SMS is: a scam to warn about ([scam]), a bank alert to count ([txn]), or neither. */
data class SmsVerdict(val scam: MessageLabel?, val txn: MoneyTxn?)

object SmsTriage {
    /**
     * Every message gets the scam check first, bank-looking ones too: "Rs 900 has been credited to
     * your account, pay Rs 2,000 to unlock Level 4" is a task-scam opener, not a bank alert. A message
     * that reads like a scam script is never counted as money, so a fake credit cannot feed the
     * task-scam watcher. OTPs are not scams here (they have their own warning) and never money.
     * [trustNumbers]: debug builds accept numbered senders as banks, so the emulator can play one.
     */
    fun triage(
        sender: String?,
        body: String,
        ts: Long,
        lure: LureClassifier,
        ai: AiTextScorer?,
        trustNumbers: Boolean,
    ): SmsVerdict {
        val label = MessageCheck.check(sender, body, ts, lure, ai, emptyList())
        val scam = label.takeIf { it.scamTag != null && !it.otp }
        val txn = if (scam == null && BankSms.trustedSender(sender, trustNumbers)) BankSms.parse(body, ts) else null
        return SmsVerdict(scam, txn)
    }
}
