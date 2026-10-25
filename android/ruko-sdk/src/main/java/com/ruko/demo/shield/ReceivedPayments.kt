package com.ruko.demo.shield

import com.ruko.demo.signals.ContactMatch
import com.ruko.demo.signals.Flow
import com.ruko.demo.signals.SavedContact

/** Money that came in, as the watcher read it from a bank SMS alert. On the phone only. */
data class ReceivedPayment(
    val ts: Long,
    val amountInr: Double,
    val sender: String?, // the UPI ID the alert named; null when it named none
    val senderName: String?, // a saved contact whose number is inside the sender's UPI ID, else the name the bank gave
)

/** The rules of the History screen's "received" rows, without Android, so ReceivedPaymentsTest can run them. */
object ReceivedPayments {
    /**
     * Credits the background watcher kept from bank SMS alerts (it keeps 30 days), oldest first.
     * Nothing while the watcher is off ([watcher] null), no debits and none of this app's own
     * payments (those are the History's payment rows). Whether the watcher counted a credit as
     * "bait" is not shown: a WATCHING episode stays silent on the phone (CLAUDE.md rule 10).
     */
    fun from(watcher: WatcherState?, contacts: List<SavedContact> = emptyList()): List<ReceivedPayment> {
        if (watcher == null) return emptyList()
        val names = contacts.associate { it.mobile to it.name }
        return watcher.history
            .filter { it.flow == Flow.IN && it.fromSms }
            .sortedBy { it.ts }
            .map { t ->
                ReceivedPayment(
                    ts = t.ts,
                    amountInr = t.amount,
                    sender = t.counterparty,
                    senderName = t.counterparty?.let(ContactMatch::mobileOfUpi)?.let(names::get) ?: t.counterpartyName,
                )
            }
    }
}
