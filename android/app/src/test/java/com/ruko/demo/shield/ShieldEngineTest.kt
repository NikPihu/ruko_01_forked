package com.ruko.demo.shield

import com.ruko.demo.signals.Flow
import com.ruko.demo.signals.MoneyTxn
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ShieldEngineTest {

    private val rules = EpisodeRules("episode-0.2", 500.0, 500.0, 1.5, 2, 2, 30, 30, 10)
    private val t0 = 1_800_000_000_000L
    private fun h(x: Double) = t0 + (x * 3_600_000).toLong()
    private fun bait(at: Double, from: String, inr: Double = 150.0) = MoneyTxn(h(at), inr, Flow.IN, from, fromSms = true)
    private fun appOut(at: Double, to: String, inr: Double) = MoneyTxn(h(at), inr, Flow.OUT, to)
    private fun smsOut(at: Double, to: String, inr: Double) = MoneyTxn(h(at), inr, Flow.OUT, to, fromSms = true)

    private fun run(data: ShieldData, txns: List<MoneyTxn>, now: Double) = ShieldEngine.apply(rules, true, data, txns, h(now))

    @Test
    fun watchingThenActiveEachNotifyOnce() {
        val first = run(ShieldData(), listOf(bait(0.0, "r1@ybl")), 0.1)
        assertEquals(listOf(ShieldEngine.AlertKind.WATCHING), first.alerts.map { it.kind })
        assertEquals(listOf("watching"), first.transitions.map { it.trigger })

        val again = run(first.data, listOf(bait(1.0, "r1@ybl", 120.0)), 1.1)
        assertTrue("same state, no new alert", again.alerts.isEmpty())

        val outs = listOf(appOut(2.0, "u1@ybl", 1_000.0), appOut(3.0, "u2@ybl", 2_500.0), appOut(4.0, "u3@ybl", 6_000.0))
        val active = run(again.data, outs, 4.1)
        assertEquals(listOf(ShieldEngine.AlertKind.ACTIVE), active.alerts.map { it.kind })
        assertEquals(EpisodeState.ACTIVE, active.data.watcher.episode.state)
        assertTrue("active" in active.transitions.map { it.trigger })
    }

    @Test
    fun atMostTwoNotificationsAWeek() {
        var d = run(ShieldData(), listOf(bait(0.0, "r1@ybl")), 0.1).data
        d = run(d, listOf(appOut(1.0, "u1@ybl", 1_000.0), appOut(2.0, "u2@ybl", 2_500.0), appOut(3.0, "u3@ybl", 6_000.0)), 3.1).data
        val third = run(d, listOf(smsOut(5.0, "u4@ybl", 15_000.0)), 5.1)
        assertTrue("third alert in a week is held back", third.alerts.isEmpty())
        assertEquals(listOf("out_payment"), third.transitions.map { it.trigger }) // the server still hears of it
    }

    @Test
    fun theSameSmsSeenTwiceCountsOnce() {
        val one = bait(0.0, "r1@ybl")
        val d = run(ShieldData(), listOf(one), 0.1).data
        val twice = run(d, listOf(one.copy(ts = one.ts + 30_000)), 0.2) // catch-up scan of the same alert
        assertEquals(1, twice.data.watcher.episode.bait.size)
    }

    @Test
    fun newBaitSenderIsATransitionButNotANotification() {
        val d = run(ShieldData(), listOf(bait(0.0, "r1@ybl")), 0.1).data
        val r = run(d, listOf(bait(1.0, "r2@ybl")), 1.1)
        assertEquals(listOf("bait"), r.transitions.map { it.trigger })
        assertTrue(r.alerts.isEmpty())
    }

    @Test
    fun dismissAndQuietClose() {
        val d = run(ShieldData(), listOf(bait(0.0, "r1@ybl")), 0.1).data
        val dismissed = ShieldEngine.dismiss(rules, true, d, h(1.0))
        assertEquals(EpisodeState.DISMISSED, dismissed.data.watcher.episode.state)
        assertEquals(listOf("dismissed"), dismissed.transitions.map { it.trigger })

        val fresh = run(ShieldData(), listOf(bait(0.0, "r1@ybl")), 0.1).data
        val closed = run(fresh, emptyList(), 31 * 24.0)
        assertEquals(EpisodeState.NONE, closed.data.watcher.episode.state)
        assertEquals(listOf("closed"), closed.transitions.map { it.trigger })
    }
}
