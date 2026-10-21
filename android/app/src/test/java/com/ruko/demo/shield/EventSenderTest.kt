package com.ruko.demo.shield

import com.ruko.demo.data.Consents
import com.ruko.demo.net.EpisodeEvent
import com.ruko.demo.net.RukoJson
import com.ruko.demo.signals.Flow
import com.ruko.demo.signals.MoneyTxn
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class EventSenderTest {

    private val rules = EpisodeRules("episode-0.2", 500.0, 500.0, 1.5, 2, 2, 30, 30, 10)
    private val t0 = 1_800_000_000_000L
    private fun h(x: Double) = t0 + (x * 3_600_000).toLong()
    private val share = Consents(smsLure = true, moneyWatch = true, shareAccounts = true)

    private val schema = generateSequence(File("").absoluteFile) { it.parentFile }
        .map { File(it, "contracts/c2_episode.schema.json") }.first { it.exists() }
        .let { Json.parseToJsonElement(it.readText()).jsonObject }

    private fun active(): ShieldEngine.Result {
        val txns = (1..12).map { MoneyTxn(h(it * 0.1), 150.0, Flow.IN, "r$it@ybl", fromSms = true) } + listOf(
            MoneyTxn(h(2.0), 1_000.0, Flow.OUT, "u1@ybl"),
            MoneyTxn(h(3.0), 2_500.0, Flow.OUT, "u2@ybl", fromSms = true),
            MoneyTxn(h(4.0), 6_000.0, Flow.OUT, "u3@ybl"),
        )
        return ShieldEngine.apply(rules, true, ShieldData(), txns, h(4.1))
    }

    @Test
    fun nothingIsQueuedWithoutSharing() {
        val r = active()
        val d = EventSender.queue(r.data, r.transitions, share.copy(shareAccounts = false), rules, true, h(4.1))
        assertTrue(d.pending.isEmpty())
    }

    @Test
    fun oneEventPerTransitionWithAtMostTenAccounts() {
        val r = active()
        val d = EventSender.queue(r.data, r.transitions, share, rules, true, h(4.1))
        assertEquals(r.transitions.size, d.pending.size)
        val events = d.pending.map { RukoJson.decodeFromString(EpisodeEvent.serializer(), it) }
        assertTrue(events.all { it.accounts.size <= EventSender.MAX_ACCOUNTS })
        val last = events.last()
        assertEquals("active", last.trigger)
        val payees = last.accounts.filter { it.role == "payee" }.associateBy { it.upiId }
        assertEquals("other_app", payees.getValue("u2@ybl").via)
        assertEquals(3, payees.getValue("u3@ybl").step)
    }

    @Test
    fun endedEpisodesSendNoAccounts() {
        val r = active()
        val dismissed = ShieldEngine.dismiss(rules, true, r.data, h(5.0))
        val d = EventSender.queue(dismissed.data, dismissed.transitions, share, rules, true, h(5.0))
        val e = RukoJson.decodeFromString(EpisodeEvent.serializer(), d.pending.single())
        assertEquals("dismissed", e.trigger)
        assertTrue(e.accounts.isEmpty())
    }

    @Test
    fun eventsUseOnlySchemaFields() {
        val r = active()
        val d = EventSender.queue(r.data, r.transitions, share, rules, true, h(4.1))
        val json = RukoJson.parseToJsonElement(d.pending.last()).jsonObject
        val req = schema.getValue("request").jsonObject
        val allowed = req.getValue("properties").jsonObject.keys
        assertTrue("not in schema: ${json.keys - allowed}", allowed.containsAll(json.keys))
        val accAllowed = req.getValue("\$defs").jsonObject.getValue("EpisodeAccount").jsonObject.getValue("properties").jsonObject.keys
        val acc = json.getValue("accounts").let { (it as kotlinx.serialization.json.JsonArray).first().jsonObject }
        assertTrue(accAllowed.containsAll(acc.keys))
    }
}
