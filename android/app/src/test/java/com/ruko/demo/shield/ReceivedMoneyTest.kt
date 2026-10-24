package com.ruko.demo.shield

import com.ruko.demo.data.Consents
import com.ruko.demo.net.RukoJson
import com.ruko.demo.net.MoneyReceived
import com.ruko.demo.signals.Flow
import com.ruko.demo.signals.MoneyTxn
import com.ruko.demo.signals.SavedContact
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Money received (c2-0.11): the History rows, what is sent, and that a repeated alert counts once. */
class ReceivedMoneyTest {
    private val rules = EpisodeRules("episode-0.2", 500.0, 500.0, 1.5, 2, 2, 30, 30, 10)
    private val t0 = 1_800_000_000_000L
    private fun m(x: Double) = t0 + (x * 60_000).toLong()
    private fun credit(at: Double, from: String?, inr: Double) = MoneyTxn(m(at), inr, Flow.IN, from, fromSms = true)

    @Test
    fun historyShowsCreditsFromBankSmsOldestFirstWithContactNames() {
        val watcher = WatcherState(history = listOf(
            credit(5.0, "priya.nair22@ybl", 1_200.0),
            credit(1.0, "9876543210@oksbi", 500.0),
            MoneyTxn(m(2.0), 900.0, Flow.OUT, "shop@ybl", fromSms = true),   // money out: a payment, not received
            MoneyTxn(m(3.0), 300.0, Flow.IN, "app@ybl"),                      // not from a bank SMS
            credit(4.0, null, 250.0),
        ))
        val rows = ReceivedPayments.from(watcher, listOf(SavedContact("Arjun Pandey", "+919876543210")))
        assertEquals(listOf(500.0, 250.0, 1_200.0), rows.map { it.amountInr })
        assertEquals("Arjun Pandey", rows[0].senderName)
        assertNull("no sender named: unknown, not made up", rows[1].sender)
        assertTrue(ReceivedPayments.from(null).isEmpty())
    }

    @Test
    fun onlyCreditsFromBankSmsAreSentAndNeverTheText() {
        val txns = listOf(
            credit(1.0, "arjun.pandey@okicici", 500.0),
            MoneyTxn(m(2.0), 900.0, Flow.OUT, "shop@ybl", fromSms = true),
            credit(3.0, null, 250.0),
        )
        var n = 0
        val events = ReceivedPolicy.events(txns, "u_demo_meena") { "e${n++}" }
        assertEquals(listOf("e0", "e1"), events.map { it.eventId })
        assertEquals(listOf("arjun.pandey@okicici", null), events.map { it.senderUpiId })
        assertEquals("bank_sms", events[0].source)
        val wire = RukoJson.encodeToString(MoneyReceived.serializer(), events[0])
        assertEquals(setOf("event_id", "user_id", "sender_upi_id", "amount_inr", "ts", "source"),
            RukoJson.parseToJsonElement(wire).let { (it as kotlinx.serialization.json.JsonObject).keys })
    }

    @Test
    fun sharingNeedsTheMoneyWatchAndItsOwnSwitchBothOffByDefault() {
        assertFalse(ReceivedPolicy.allowed(Consents()))
        assertFalse(ReceivedPolicy.allowed(Consents(moneyWatch = true)))
        assertFalse(ReceivedPolicy.allowed(Consents(shareReceived = true)))
        assertTrue(ReceivedPolicy.allowed(Consents(smsLure = true, moneyWatch = true, shareReceived = true)))
    }

    @Test
    fun theWatcherHandsOnACreditOnceEvenWhenTheAlertArrivesTwice() {
        val sms = credit(1.0, "arjun.pandey@okicici", 500.0)
        val first = ShieldEngine.apply(rules, true, ShieldData(), listOf(sms), m(1.5))
        assertEquals(listOf(sms), first.fresh)
        // The SMS receiver and the catch-up scan can both see the same alert.
        val again = ShieldEngine.apply(rules, true, first.data, listOf(sms.copy(ts = sms.ts + 30_000)), m(2.0))
        assertTrue(again.fresh.isEmpty())
    }
}
