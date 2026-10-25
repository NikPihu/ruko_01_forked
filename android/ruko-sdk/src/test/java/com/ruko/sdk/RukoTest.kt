package com.ruko.sdk

import com.ruko.demo.net.DecideResponse
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException

/** Rule 3: the SDK never blocks a payment because RUKO failed. */
class RukoTest {

    private fun answer(id: String = "p1", failOpen: Boolean = false) =
        DecideResponse(requestId = id, tier = "T3", reasons = listOf("R3_mule_like_payee"), failOpen = failOpen)

    @Test
    fun aServerAnswerPassesThrough() = runBlocking {
        val d = Ruko.decideOrFailOpen("p1") { answer() }
        assertTrue(d is RukoDecision.Checked)
        assertEquals("T3", (d as RukoDecision.Checked).response.tier)
    }

    @Test
    fun anErrorOrTimeoutIsUnavailable() = runBlocking {
        assertEquals(RukoDecision.Unavailable, Ruko.decideOrFailOpen("p1") { throw IOException("timeout") })
    }

    @Test
    fun theServersOwnFailOpenIsUnavailable() = runBlocking {
        assertEquals(RukoDecision.Unavailable, Ruko.decideOrFailOpen("p1") { answer(failOpen = true) })
    }

    @Test
    fun anAnswerForAnotherPaymentIsNotUsed() = runBlocking {
        assertEquals(RukoDecision.Unavailable, Ruko.decideOrFailOpen("p1") { answer(id = "p2") })
    }
}
