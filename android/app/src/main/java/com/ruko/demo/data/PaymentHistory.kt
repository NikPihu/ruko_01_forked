package com.ruko.demo.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
enum class PaymentState {
    @SerialName("pending") PENDING, // checked, the user is still on the decision or PIN screen
    @SerialName("completed") COMPLETED,
    @SerialName("cancelled") CANCELLED,
}

/**
 * One payment the user started, kept on the phone (encrypted, see [AccountStore]).
 * [id] is the payment id: the same UUID the app sent as the /v1/decide `request_id`, so one payment
 * can be traced from this list to the server's evidence and the analyst console.
 */
@Serializable
data class PaymentRecord(
    val id: String,
    val ts: Long, // when Pay was tapped, epoch millis
    val payee: String,
    @SerialName("payee_name") val payeeName: String? = null, // the contact's name, or the bank's registered name
    @SerialName("amount_inr") val amountInr: Double,
    @SerialName("entry_method") val entryMethod: String, // typed, contact, qr, collect
    val tier: String? = null, // Scam Shield's decision; null = safety check unavailable
    val reasons: List<String> = emptyList(),
    @SerialName("evidence_id") val evidenceId: String? = null,
    val state: PaymentState = PaymentState.PENDING,
    @SerialName("outcome_ts") val outcomeTs: Long? = null,
    val reported: Boolean = false, // the server has the outcome (POST /v1/payment/outcome)
)

/** The rules of the history list, without Android, so PaymentHistoryTest can run them. Oldest first. */
object PaymentHistory {
    const val KEEP_MS = 90L * 24 * 60 * 60_000
    const val MAX = 500

    /** A new check. Only one payment is in progress at a time: an older pending one was left unpaid. */
    fun add(list: List<PaymentRecord>, record: PaymentRecord, now: Long): List<PaymentRecord> =
        trim(closeAbandoned(list.filter { it.id != record.id }, now) + record, now)

    /** The PIN was entered or the user tapped Cancel. Only a pending payment changes. */
    fun settle(list: List<PaymentRecord>, id: String, state: PaymentState, now: Long): List<PaymentRecord> =
        list.map { if (it.id == id && it.state == PaymentState.PENDING) it.copy(state = state, outcomeTs = now) else it }

    /** Payments left on the decision or PIN screen (back button, app closed) count as cancelled. */
    fun closeAbandoned(list: List<PaymentRecord>, now: Long): List<PaymentRecord> =
        list.map { if (it.state == PaymentState.PENDING) it.copy(state = PaymentState.CANCELLED, outcomeTs = now) else it }

    /** Finished payments whose outcome the server does not have yet. */
    fun toReport(list: List<PaymentRecord>): List<PaymentRecord> =
        list.filter { it.state != PaymentState.PENDING && !it.reported }

    fun markReported(list: List<PaymentRecord>, ids: Set<String>): List<PaymentRecord> =
        list.map { if (it.id in ids) it.copy(reported = true) else it }

    fun trim(list: List<PaymentRecord>, now: Long): List<PaymentRecord> =
        list.filter { now - it.ts <= KEEP_MS }.takeLast(MAX)
}
