package com.ruko.demo.signals

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SignalsTest {

    @Test
    fun charWbMatchesScikitLearn() {
        // sklearn: TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5)).build_analyzer()("hi")
        assertEquals(listOf(" hi", "hi ", " hi "), charWbNgrams("hi", 3, 5))
        val grams = charWbNgrams("arrest", 3, 5)
        assertEquals(" ar", grams.first())
        assertTrue(" arre" in grams && "rest " in grams)
        assertEquals(6 + 5 + 4, grams.size)
    }

    @Test
    fun linearModelPicksTheHeavierClass() {
        val model = LureModel(
            version = "test",
            ngramRange = listOf(3, 5),
            classes = listOf("arrest_threat", "normal"),
            vocabulary = mapOf(" ar" to 0, "arr" to 1, " hi" to 2),
            idf = listOf(1.0, 1.0, 1.0),
            coef = listOf(listOf(4.0, 4.0, -2.0), listOf(-4.0, -4.0, 2.0)),
            intercept = listOf(0.0, 0.0),
        )
        val hit = LinearLureClassifier(model).classify("ARREST warrant")
        assertEquals("arrest_threat", hit.tag)
        assertTrue(hit.conf > 0.9)
        assertEquals("normal", LinearLureClassifier(model).classify("hi").tag)
    }

    @Test
    fun keywordFallbackNeedsMoreThanOneWord() {
        val scam = KeywordLureClassifier.classify("This is CBI. A warrant for your arrest is issued.")
        assertEquals("arrest_threat", scam.tag)
        assertTrue(scam.conf >= LURE_SEND_THRESHOLD)
        assertTrue(KeywordLureClassifier.classify("Your refund is processed").conf < LURE_SEND_THRESHOLD)
        assertEquals("normal", KeywordLureClassifier.classify("Dinner at 8?").tag)
    }

    @Test
    fun onlyStrongScamTagsAreSent() {
        val tags = bestLureTags(
            listOf(LureHit("kyc", 0.7), LureHit("kyc", 0.9), LureHit("refund", 0.5), LureHit("normal", 0.99)),
        )
        assertEquals(listOf("kyc"), tags.map { it.tag })
        assertEquals(0.9, tags.single().conf, 0.0)
    }

    @Test
    fun switchedOffCallSignalsSendNullContext() {
        assertNull(PhoneSignals(call = null, device = null).toRequestContext())
    }

    @Test
    fun unknownCallerIsNeverSafe() {
        val voipCall = CallReading(
            active = true, kind = CallKind.VOIP, direction = null,
            callerInContacts = null, startedMinAgo = 38.4, endedMinAgo = null,
        )
        val context = PhoneSignals(voipCall, device = null).toRequestContext()!!
        assertTrue(context.onCall)
        assertEquals(false, context.callerInContacts)
        assertEquals(38, context.callMinutes)
    }

    @Test
    fun overridesFillOnlyConsentedGroupsAndAreListed() {
        val o = SignalOverrides(onCall = true, callMinutes = 38, remoteApp = true)
        val real = PhoneSignals(
            call = CallReading(false, null, null, null, null, null),
            device = null, // app checks switched off
        )
        val applied = o.applyTo(real)
        assertEquals(true, applied.call!!.active)
        assertEquals(38.0, applied.call!!.startedMinAgo!!, 0.0)
        assertNull(applied.device)
        assertEquals(listOf("on_call", "call_minutes", "remote_access_app"), o.active)
    }
}
