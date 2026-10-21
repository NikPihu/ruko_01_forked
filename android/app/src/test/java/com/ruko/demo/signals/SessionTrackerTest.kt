package com.ruko.demo.signals

import com.ruko.demo.net.SessionSignal
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The Pay-screen session (contract c2-0.5), driven with made-up times in milliseconds. */
class SessionTrackerTest {

    /** Types [amount] one digit at a time, [gapMs] apart, starting at [from]; returns the end time. */
    private fun SessionTracker.typeAmount(amount: String, from: Long, gapMs: Long): Long {
        var text = ""
        var t = from
        for (c in amount) {
            onAmountChange(text, text + c, t)
            text += c
            t += gapMs
        }
        return t - gapMs
    }

    @Test
    fun dictatedAmountShowsLongGaps() {
        val s = SessionTracker().apply { start(0) }
        val end = s.typeAmount("95000", from = 10_000, gapMs = 2_400)
        val sig = s.toSignal(end + 1_000, usualGaps = listOf(0.5, 0.4, 0.5))
        assertEquals(5, sig.amountDigits)
        assertEquals(2.4, sig.amountMedianGapS!!, 0.0)
        assertEquals(4.8, sig.amountGapVsUsual!!, 0.0)
    }

    @Test
    fun noBaselineMeansUnknownNotCalm() {
        val s = SessionTracker().apply { start(0) }
        s.typeAmount("500", from = 1_000, gapMs = 300)
        val sig = s.toSignal(5_000, usualGaps = listOf(0.4, 0.5)) // only two past payments
        assertNull(sig.amountGapVsUsual)
        assertEquals(0.3, sig.amountMedianGapS!!, 0.0)
    }

    @Test
    fun pasteRightAfterComingBackIsTimed() {
        val s = SessionTracker().apply { start(0) }
        s.onBackground(5_000)          // goes to WhatsApp
        s.onForeground(35_000)         // back after 30 s
        s.onPayeeChange("", "secure.settlement.desk@okaxis", 41_000)
        val sig = s.toSignal(60_000, emptyList())
        assertEquals(true, sig.payeePasted)
        assertEquals(6.0, sig.pastedWithinSOfReturn!!, 0.0)
        assertEquals(1, sig.appSwitches)
        assertEquals(30.0, sig.awayS!!, 0.0)
        assertEquals(60.0, sig.payScreenS!!, 0.0)
    }

    @Test
    fun typingTheUpiIdIsNotAPaste() {
        val s = SessionTracker().apply { start(0) }
        var text = ""
        "ravi@okaxis".forEachIndexed { i, c -> s.onPayeeChange(text, text + c, 100L * i); text += c }
        val sig = s.toSignal(5_000, emptyList())
        assertFalse(sig.payeePasted!!)
        assertNull(sig.pastedWithinSOfReturn)
    }

    @Test
    fun pasteWithoutLeavingTheAppHasNoReturnTime() {
        val s = SessionTracker().apply { start(0) }
        s.onPayeeChange("", "shop.owner@ybl", 2_000)
        val sig = s.toSignal(5_000, emptyList())
        assertTrue(sig.payeePasted!!)
        assertNull(sig.pastedWithinSOfReturn)
        assertEquals(0, sig.appSwitches)
    }

    @Test
    fun deletionsCountAsEdits() {
        val s = SessionTracker().apply { start(0) }
        s.onAmountChange("", "9", 1_000)
        s.onAmountChange("9", "95", 1_500)
        s.onAmountChange("95", "9", 2_000)
        assertEquals(1, s.toSignal(3_000, emptyList()).amountEdits)
    }

    @Test
    fun leftUnpaidFlowsCountForThirtyMinutes() {
        val s = SessionTracker()
        s.start(0)
        s.typeAmount("5000", from = 1_000, gapMs = 500)
        s.start(60_000)                                      // back to Home, then Pay again
        assertEquals(1, s.toSignal(70_000, emptyList()).abandonedFlows30m)
        s.start(120_000)                                     // an empty visit is not a try
        assertEquals(1, s.toSignal(130_000, emptyList()).abandonedFlows30m)
        assertEquals(0, s.toSignal(60_000 + 31 * 60_000L, emptyList()).abandonedFlows30m)
    }

    @Test
    fun paidFlowIsNotAbandoned() {
        val s = SessionTracker()
        s.start(0)
        s.typeAmount("200", from = 1_000, gapMs = 300)
        s.markPaid()
        s.start(10_000)
        assertEquals(0, s.toSignal(11_000, emptyList()).abandonedFlows30m)
    }

    @Test
    fun overrideReplacesTheRealSession() {
        val calm = SessionSignal(amountDigits = 3)
        assertEquals(calm, SignalOverrides().applyTo(calm))
        assertEquals(true, SignalOverrides(coachedSession = true).applyTo(calm)!!.payeePasted)
        assertEquals(SignalOverrides.CALM_SESSION, SignalOverrides(coachedSession = false).applyTo(null))
    }
}
