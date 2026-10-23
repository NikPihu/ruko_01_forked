package com.ruko.demo.shield

import com.ruko.demo.data.Consents
import com.ruko.demo.net.CallKind
import com.ruko.demo.net.RukoJson
import com.ruko.demo.net.WatchEvent
import com.ruko.demo.net.WatchKind
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** Early warnings (Step 7): thresholds from contracts/watch_rules.json, quiet periods, consents, no text. */
class WatchPolicyTest {
    private val repo: File = generateSequence(File("").absoluteFile) { it.parentFile }
        .first { File(it, "contracts/watch_rules.json").exists() }
    private val rules = WatchRules.parse(File(repo, "contracts/watch_rules.json").readText())
    private val now = 1_800_000_000_000L
    private val none = emptyMap<String, Long>()

    @Test
    fun assetIsTheContractCopy() {
        assertEquals(
            File(repo, "contracts/watch_rules.json").readText(),
            File(repo, "android/app/src/main/assets/watch_rules.json").readText(),
        )
    }

    @Test
    fun lureNeedsTheSendThresholdAndKeepsQuietAfter() {
        assertNull(WatchPolicy.event(Sighting.Lure("kyc", 0.4, "sms", null), rules, now, none))
        assertNull(WatchPolicy.event(Sighting.Lure("normal", 0.99, "sms", null), rules, now, none))
        val (e, key) = WatchPolicy.event(Sighting.Lure("kyc", 0.876, "notification", true), rules, now, none)!!
        assertEquals(WatchKind.LURE_SEEN, e.kind)
        assertEquals("kyc", e.lureTag)
        assertEquals(0.88, e.lureConf!!, 1e-9)
        assertEquals("notification", e.source)
        assertEquals(true, e.aiWritten)

        val quiet = (rules.lureRepeatQuietMin * 60_000).toLong()
        assertNull(WatchPolicy.event(Sighting.Lure("kyc", 0.9, "sms", null), rules, now + quiet - 1, mapOf(key to now)))
        assertNotNull(WatchPolicy.event(Sighting.Lure("kyc", 0.9, "sms", null), rules, now + quiet, mapOf(key to now)))
        // Another scam type is a new warning.
        assertNotNull(WatchPolicy.event(Sighting.Lure("refund", 0.9, "sms", null), rules, now + 1, mapOf(key to now)))
    }

    @Test
    fun longCallMustBeLongAndUnknown() {
        val long = rules.longCallMin + 1
        assertNotNull(WatchPolicy.event(Sighting.LongCall(CallKind.SIM, long, false), rules, now, none))
        assertNotNull(WatchPolicy.event(Sighting.LongCall(CallKind.VOIP, long, null), rules, now, none))
        assertNull(WatchPolicy.event(Sighting.LongCall(CallKind.SIM, long, true), rules, now, none))
        assertNull(WatchPolicy.event(Sighting.LongCall(CallKind.SIM, long, null), rules, now, none)) // same as the server
        assertNull(WatchPolicy.event(Sighting.LongCall(CallKind.VOIP, rules.longCallMin - 1, null), rules, now, none))
        val e = WatchPolicy.event(Sighting.LongCall(CallKind.VOIP, 23.46, null), rules, now, none)!!.first
        assertEquals(WatchKind.LONG_UNKNOWN_CALL, e.kind)
        assertEquals(23.5, e.callMinutes!!, 1e-9)
        // Every long call counts, even right after another.
        assertNotNull(WatchPolicy.event(Sighting.LongCall(CallKind.VOIP, long, null), rules, now + 1, mapOf("call" to now)))
    }

    @Test
    fun deviceWarningsOnlyForRecentChanges() {
        val recent = rules.deviceRecentHours * 60
        assertNotNull(WatchPolicy.event(Sighting.RemoteApp(30.0), rules, now, none))
        assertNull(WatchPolicy.event(Sighting.RemoteApp(recent + 1), rules, now, none))
        assertNull(WatchPolicy.event(Sighting.RemoteApp(null), rules, now, none))
        assertNotNull(WatchPolicy.event(Sighting.Sideload(true), rules, now, none))
        assertNull(WatchPolicy.event(Sighting.Sideload(null), rules, now, none))
        assertNull(WatchPolicy.event(Sighting.RemoteApp(30.0), rules, now + 60_000, mapOf("remote" to now)))
    }

    @Test
    fun everyWarningNeedsEarlyWarningsAndItsOwnSwitch() {
        val lureSms = Sighting.Lure("kyc", 0.9, "sms", null)
        val lureChat = Sighting.Lure("kyc", 0.9, "notification", null)
        val off = Consents()
        assertFalse(off.earlyWarnings) // off by default
        assertFalse(off.chatLure)
        assertFalse(WatchPolicy.allowed(lureSms, off.copy(smsLure = true)))
        val on = off.copy(earlyWarnings = true)
        assertFalse(WatchPolicy.allowed(lureSms, on))
        assertTrue(WatchPolicy.allowed(lureSms, on.copy(smsLure = true)))
        assertFalse(WatchPolicy.allowed(lureChat, on.copy(smsLure = true)))
        assertTrue(WatchPolicy.allowed(lureChat, on.copy(chatLure = true)))
        assertFalse(WatchPolicy.allowed(Sighting.LongCall(CallKind.SIM, 30.0, false), on.copy(callSignals = false)))
        assertFalse(WatchPolicy.allowed(Sighting.Sideload(true), on.copy(appChecks = false)))
    }

    @Test
    fun eventsCarryTagsAndCountsOnly() {
        val allowed = setOf("event_id", "user_id", "kind", "ts", "lure_tag", "lure_conf", "source", "ai_written", "call_kind", "call_minutes")
        val sightings = listOf(
            Sighting.Lure("arrest_threat", 0.95, "sms", false),
            Sighting.LongCall(CallKind.VOIP, 40.0, null),
            Sighting.RemoteApp(5.0),
            Sighting.Sideload(true),
        )
        for (s in sightings) {
            val e = WatchPolicy.event(s, rules, now, none)!!.first
            val keys = Json.parseToJsonElement(RukoJson.encodeToString(WatchEvent.serializer(), e)).jsonObject.keys
            assertTrue("$keys", allowed.containsAll(keys))
            assertTrue(e.ts.endsWith("+05:30"))
        }
    }
}
