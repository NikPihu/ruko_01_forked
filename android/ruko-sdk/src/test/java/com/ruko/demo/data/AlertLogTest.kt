package com.ruko.demo.data

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** The Alerts screen's list: newest first, repeats folded, old ones dropped, never message text. */
class AlertLogTest {

    private val t0 = 1_760_000_000_000L
    private fun scam(ts: Long, tag: String = "task_job", source: String = "sms") =
        AlertEntry(ts, AlertKind.SCAM_MESSAGE, tag, source)

    @Test
    fun newestFirst() {
        var f = AlertLogFile()
        f = AlertLog.add(f, scam(t0))
        f = AlertLog.add(f, AlertEntry(t0 + 60 * 60_000, AlertKind.OTP_ON_CALL))
        assertEquals(listOf(AlertKind.OTP_ON_CALL, AlertKind.SCAM_MESSAGE), f.entries.map { it.kind })
    }

    @Test
    fun theSameWarningWithinTenMinutesIsOneAlert() {
        var f = AlertLog.add(AlertLogFile(), scam(t0))
        f = AlertLog.add(f, scam(t0 + 5 * 60_000))                 // the same scam SMS in parts
        assertEquals(1, f.entries.size)
        f = AlertLog.add(f, scam(t0 + 6 * 60_000, tag = "kyc"))     // a different scam type is new
        f = AlertLog.add(f, scam(t0 + 7 * 60_000, source = "chat")) // so is the same one in a chat
        f = AlertLog.add(f, scam(t0 + 30 * 60_000))                 // and the first one again later
        assertEquals(4, f.entries.size)
    }

    @Test
    fun oldAndExtraAlertsAreDropped() {
        var f = AlertLogFile()
        for (i in 0 until AlertLog.MAX + 20) f = AlertLog.add(f, scam(t0 + i * AlertLog.REPEAT_MS * 2))
        assertEquals(AlertLog.MAX, f.entries.size)
        val later = f.entries.first().ts + AlertLog.KEEP_MS + 1
        assertEquals(0, AlertLog.trim(f.entries, later).size)
    }

    @Test
    fun unseenCountsOnlyAlertsAfterTheLastLook() {
        var f = AlertLog.add(AlertLogFile(), scam(t0))
        f = f.copy(seenAt = t0 + 1)
        f = AlertLog.add(f, AlertEntry(t0 + 60_000, AlertKind.TASK_SCAM))
        assertEquals(1, AlertLog.unseen(f))
    }

    @Test
    fun storedFormHasNoMessageTextOrSender() {
        val file = AlertLog.add(AlertLogFile(), scam(t0).copy(aiWritten = true)).copy(seenAt = t0)
        val json = Json.encodeToString(AlertLogFile.serializer(), file)
        val root = Json.parseToJsonElement(json).jsonObject
        assertTrue(setOf("entries", "seen_at").containsAll(root.keys))
        assertTrue(setOf("ts", "kind", "tag", "source", "ai_written").containsAll(root["entries"]!!.jsonArray.single().jsonObject.keys))
        assertFalse(json.contains("body") || json.contains("text") || json.contains("sender"))
    }
}
