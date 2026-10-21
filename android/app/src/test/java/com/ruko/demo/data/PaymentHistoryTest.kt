package com.ruko.demo.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PaymentHistoryTest {

    private val t0 = 1_793_000_000_000L
    private fun rec(id: String, at: Long = t0, tier: String? = "T0") =
        PaymentRecord(id = id, ts = at, payee = "shreeganesh.kirana@okaxis", amountInr = 240.0, entryMethod = "qr", tier = tier)

    @Test
    fun checkThenPinIsCompletedAndWaitsToBeReported() {
        var h = PaymentHistory.add(emptyList(), rec("p1"), t0)
        assertEquals(PaymentState.PENDING, h.single().state)
        assertTrue("nothing to report while pending", PaymentHistory.toReport(h).isEmpty())
        h = PaymentHistory.settle(h, "p1", PaymentState.COMPLETED, t0 + 5_000)
        assertEquals(PaymentState.COMPLETED, h.single().state)
        assertEquals(t0 + 5_000, h.single().outcomeTs)
        assertEquals(listOf("p1"), PaymentHistory.toReport(h).map { it.id })
        h = PaymentHistory.markReported(h, setOf("p1"))
        assertTrue(PaymentHistory.toReport(h).isEmpty())
    }

    @Test
    fun aFinishedPaymentNeverChangesAgain() {
        var h = PaymentHistory.add(emptyList(), rec("p1"), t0)
        h = PaymentHistory.settle(h, "p1", PaymentState.CANCELLED, t0 + 1)
        h = PaymentHistory.settle(h, "p1", PaymentState.COMPLETED, t0 + 2)
        assertEquals(PaymentState.CANCELLED, h.single().state)
    }

    @Test
    fun aNewCheckClosesThePaymentLeftUnpaid() {
        var h = PaymentHistory.add(emptyList(), rec("p1"), t0)
        h = PaymentHistory.add(h, rec("p2", t0 + 60_000), t0 + 60_000) // back from the PIN, tapped Pay again
        assertEquals(listOf(PaymentState.CANCELLED, PaymentState.PENDING), h.map { it.state })
        assertEquals(listOf("p1"), PaymentHistory.toReport(h).map { it.id })
    }

    @Test
    fun eachPaymentKeepsItsOwnIdAndUnavailableHasNoTier() {
        val h = PaymentHistory.add(PaymentHistory.add(emptyList(), rec("p1"), t0), rec("p2", tier = null), t0)
        assertEquals(listOf("p1", "p2"), h.map { it.id })
        assertEquals(null, h.last().tier)
    }

    @Test
    fun keepsNinetyDaysAndAtMostFiveHundred() {
        val old = rec("old", t0 - PaymentHistory.KEEP_MS - 1).copy(state = PaymentState.COMPLETED)
        assertTrue(PaymentHistory.trim(listOf(old, rec("new")), t0).none { it.id == "old" })
        val many = (1..600).map { rec("p$it").copy(state = PaymentState.COMPLETED) }
        val kept = PaymentHistory.trim(many, t0)
        assertEquals(PaymentHistory.MAX, kept.size)
        assertEquals("p600", kept.last().id)
    }
}
