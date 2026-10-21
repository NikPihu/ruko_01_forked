package com.ruko.demo.signals

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * The payer's own money flow, read on the phone to catch the task scam: small "rewards" come in
 * from strangers, then each payment out is bigger than the last ("pay 8,000 to unlock 12,000").
 * Transactions stay on the phone; shield/EpisodeTracker turns them into the counts that are sent.
 */

enum class Flow { IN, OUT }

/** One payment, from this app's history or a bank SMS alert. */
@Serializable
data class MoneyTxn(
    val ts: Long,
    val amount: Double,
    val flow: Flow,
    val counterparty: String? = null, // a UPI ID when the alert names one
    @SerialName("from_sms") val fromSms: Boolean = false,
)

/** Reads UPI credit and debit alerts in the formats Indian banks commonly send. */
object BankSms {
    private val AMOUNT = Regex("""(?:\b(?:rs\.?|inr)|₹)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)""", RegexOption.IGNORE_CASE)
    private val AMOUNT_AFTER_VERB = Regex("""(?:debited|credited)\s+(?:by|with|for)\s+([0-9][0-9,]*(?:\.[0-9]{1,2})?)""", RegexOption.IGNORE_CASE)
    private val VPA = Regex("""[a-z0-9][a-z0-9._-]{1,63}@[a-z]{2,20}""", RegexOption.IGNORE_CASE)
    private val CREDIT = Regex("""\b(credited|received|deposited)\b""", RegexOption.IGNORE_CASE)
    private val DEBIT = Regex("""\b(debited|sent|paid|transferred|withdrawn)\b""", RegexOption.IGNORE_CASE)
    private val BANK_WORDS = Regex("""\b(a/c|acct|account|upi|vpa|imps|bank)\b""", RegexOption.IGNORE_CASE)
    // Not money that moved: OTPs, requests, future debits, promotions.
    private val SKIP = Regex(
        """\b(otp|will be debited|requested|request from|collect request|is due|offer|cashback|refund|reversal|reversed|interest)\b""",
        RegexOption.IGNORE_CASE,
    )

    fun parse(body: String, ts: Long): MoneyTxn? {
        if (!BANK_WORDS.containsMatchIn(body) || SKIP.containsMatchIn(body)) return null
        val credit = CREDIT.find(body)
        val debit = DEBIT.find(body)
        val flow = when {
            credit != null && (debit == null || credit.range.first < debit.range.first) -> Flow.IN
            debit != null -> Flow.OUT
            else -> return null
        }
        val raw = AMOUNT.find(body)?.groupValues?.get(1) ?: AMOUNT_AFTER_VERB.find(body)?.groupValues?.get(1) ?: return null
        val amount = raw.replace(",", "").toDoubleOrNull()?.takeIf { it > 0 } ?: return null
        return MoneyTxn(ts, amount, flow, VPA.find(body)?.value?.lowercase(), fromSms = true)
    }

    /**
     * Banks send alerts from registered sender IDs such as "AX-HDFCBK", never from a phone
     * number. A "credited" SMS from a number is itself a scam trick, so it is not counted.
     */
    fun trustedSender(address: String?, allowNumbers: Boolean = false): Boolean {
        val a = address?.trim().orEmpty()
        if (a.isEmpty()) return false
        return allowNumbers || a.any(Char::isLetter)
    }
}
