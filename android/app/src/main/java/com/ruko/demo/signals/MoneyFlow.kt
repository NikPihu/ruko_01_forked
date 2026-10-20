package com.ruko.demo.signals

import com.ruko.demo.net.MoneySignal
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * The payer's own money flow, read on the phone to catch the task scam: small "rewards" come in
 * from strangers, then each payment out is bigger than the last ("pay 8,000 to unlock 12,000").
 * Transactions stay on the phone; only the counts in [MoneySignal] are sent.
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

object MoneyFlow {
    const val WINDOW_MS = 72 * 60 * 60_000L
    const val BAIT_MAX_INR = 500.0
    const val ESCALATION_FACTOR = 1.5
    private const val SAME_PAYMENT_MS = 10 * 60_000L

    /**
     * Summary for the request. [smsRead] is false when SMS checks are off: credits are then
     * unknown (null), and only this app's own payments are counted.
     * [paidBefore] is every UPI ID this user paid before the 72 h window.
     */
    fun summarise(txns: List<MoneyTxn>, now: Long, smsRead: Boolean, paidBefore: Set<String> = emptySet()): MoneySignal {
        val recent = dedupe(txns.filter { now - it.ts in 0..WINDOW_MS }).sortedBy { it.ts }
        val outs = recent.filter { it.flow == Flow.OUT }
        val ins = recent.filter { it.flow == Flow.IN }
        val paid = paidBefore + outs.mapNotNull { it.counterparty }
        val bait = ins.count { it.amount <= BAIT_MAX_INR && (it.counterparty == null || it.counterparty !in paid) }
        val newPayees = outs.mapNotNull { it.counterparty }.toSet().count { it !in paidBefore }
        return MoneySignal(
            baitCredits = if (smsRead) bait else null,
            creditsInr = if (smsRead) ins.sumOf { it.amount } else null,
            debits = outs.size,
            debitsInr = outs.sumOf { it.amount },
            newPayees = newPayees,
            escalationSteps = escalationSteps(outs.map { it.amount }),
            lastDebitInr = outs.lastOrNull()?.amount,
        )
    }

    /** How many payments in a row, ending with the latest, were each >= 1.5x the one before. */
    fun escalationSteps(amounts: List<Double>): Int {
        var steps = 0
        for (i in amounts.lastIndex downTo 1) {
            if (amounts[i] >= ESCALATION_FACTOR * amounts[i - 1]) steps++ else break
        }
        return steps
    }

    /** A payment made in this app also arrives as a bank debit SMS; count it once. */
    private fun dedupe(txns: List<MoneyTxn>): List<MoneyTxn> {
        val app = txns.filter { !it.fromSms }
        val sms = txns.filter { s ->
            s.fromSms && app.none { a ->
                a.flow == s.flow && a.amount == s.amount && kotlin.math.abs(a.ts - s.ts) <= SAME_PAYMENT_MS
            }
        }
        return app + sms
    }
}
