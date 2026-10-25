package com.ruko.demo.shield

import com.ruko.demo.data.Consents
import com.ruko.demo.net.CallKind
import com.ruko.demo.net.Handle
import com.ruko.demo.net.RukoJson
import com.ruko.demo.net.WatchEvent
import com.ruko.demo.net.WatchKind
import com.ruko.demo.signals.OtpPurpose
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
        assertNull(WatchPolicy.event(Sighting.Lure("kyc", rules.lureMinConf - 0.05, "sms", null), rules, now, none))
        assertNull(WatchPolicy.event(Sighting.Lure("normal", 0.99, "sms", null), rules, now, none))
        // lure-0.2: "unclear" is never a lure_seen, whatever its confidence; other_scam is a scam tag.
        assertNull(WatchPolicy.event(Sighting.Lure("unclear", 0.99, "sms", null), rules, now, none))
        assertEquals("other_scam", WatchPolicy.event(Sighting.Lure("other_scam", 0.9, "sms", null), rules, now, none)!!.first.lureTag)
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
        val allowed = setOf("event_id", "user_id", "kind", "ts", "lure_tag", "lure_conf", "source", "ai_written", "call_kind", "call_minutes", "handles", "caller_hash", "otp_purpose")
        val sightings = listOf(
            Sighting.Lure("arrest_threat", 0.95, "sms", false),
            Sighting.LongCall(CallKind.VOIP, 40.0, null),
            Sighting.RemoteApp(5.0),
            Sighting.Sideload(true),
            Sighting.OtpOnCall(CallKind.SIM, false, NUMBER_HASH, OtpPurpose.BANK),
        )
        for (s in sightings) {
            val e = WatchPolicy.event(s, rules, now, none)!!.first
            val keys = Json.parseToJsonElement(RukoJson.encodeToString(WatchEvent.serializer(), e)).jsonObject.keys
            assertTrue("$keys", allowed.containsAll(keys))
            assertTrue(e.ts.endsWith("+05:30"))
        }
    }

    @Test
    fun lureCarriesHandlesAndNewHandlesAreNotSilenced() {
        val upi = listOf(Handle("upi", "kyc.refund.desk@ybl"))
        val (e, key) = WatchPolicy.event(Sighting.Lure("kyc", 0.9, "sms", null, upi), rules, now, none)!!
        assertEquals(upi, e.handles)
        // The same scam type with the same handles keeps quiet...
        assertNull(WatchPolicy.event(Sighting.Lure("kyc", 0.9, "sms", null, upi), rules, now + 1, mapOf(key to now)))
        // ...but a new UPI ID in the same kind of scam is reported: the server counts it across phones.
        val other = listOf(Handle("upi", "other.desk@ybl"))
        assertNotNull(WatchPolicy.event(Sighting.Lure("kyc", 0.9, "sms", null, other), rules, now + 1, mapOf(key to now)))
        // No handles: the event says nothing about them (null, not an empty list).
        assertNull(WatchPolicy.event(Sighting.Lure("refund", 0.9, "sms", null), rules, now, none)!!.first.handles)
    }

    @Test
    fun anOtpOnACallIsReportedWithTheCallersPseudonymOnly() {
        val e = WatchPolicy.event(Sighting.OtpOnCall(CallKind.SIM, false, NUMBER_HASH, OtpPurpose.UPI), rules, now, none)!!.first
        assertEquals(WatchKind.OTP_DURING_CALL, e.kind)
        assertEquals(NUMBER_HASH, e.callerHash)
        assertEquals("upi", e.otpPurpose)
        val wire = RukoJson.encodeToString(WatchEvent.serializer(), e)
        assertFalse(wire, "9812345670" in wire)
        // A saved contact asking for the code is not this warning; an unseen caller still counts (rule 1).
        assertNull(WatchPolicy.event(Sighting.OtpOnCall(CallKind.SIM, true, purpose = OtpPurpose.BANK), rules, now, none))
        assertNotNull(WatchPolicy.event(Sighting.OtpOnCall(null, null, purpose = OtpPurpose.BANK), rules, now, none))
        // Every OTP on a call counts: no quiet period.
        assertNotNull(WatchPolicy.event(Sighting.OtpOnCall(CallKind.VOIP, null, purpose = OtpPurpose.UPI), rules, now + 1, mapOf("otp" to now)))
        // An OTP for an order, a social app, or one whose purpose is unclear is never reported.
        for (p in listOf(OtpPurpose.OTHER, OtpPurpose.UNKNOWN)) {
            assertNull(WatchPolicy.event(Sighting.OtpOnCall(CallKind.SIM, false, NUMBER_HASH, p), rules, now, none))
        }
    }

    @Test
    fun otpOnCallNeedsCallSignalsAndSmsScamCheck() {
        val on = Consents(earlyWarnings = true, smsLure = true, callSignals = true)
        val otp = Sighting.OtpOnCall(CallKind.SIM, false)
        assertTrue(WatchPolicy.allowed(otp, on))
        assertFalse(WatchPolicy.allowed(otp, on.copy(callSignals = false)))
        assertFalse(WatchPolicy.allowed(otp, on.copy(smsLure = false)))
        assertFalse(WatchPolicy.allowed(otp, on.copy(earlyWarnings = false)))
    }

    @Test
    fun aLongCallFromAnUnknownNumberCarriesItsPseudonym() {
        val e = WatchPolicy.event(Sighting.LongCall(CallKind.SIM, 12.0, false, NUMBER_HASH), rules, now, none)!!.first
        assertEquals(NUMBER_HASH, e.callerHash)
        // Only a non-contact SIM number is hashed; a contact or a VoIP call has none.
        assertEquals(NUMBER_HASH, com.ruko.demo.signals.callerHash(false, "+91 98123 45670"))
        assertNull(com.ruko.demo.signals.callerHash(true, "+91 98123 45670"))
        assertNull(com.ruko.demo.signals.callerHash(null, "+91 98123 45670"))
        assertNull(com.ruko.demo.signals.callerHash(false, null))
    }

    private companion object {
        // contracts/examples/watch_event_otp_on_call.json: the server's pseudonym for +919812345670.
        const val NUMBER_HASH = "sha256:3f37179d85d63e29ae717e9d95e991b1c2edd6dec24434d5b66af0b041604a63"
    }
}
