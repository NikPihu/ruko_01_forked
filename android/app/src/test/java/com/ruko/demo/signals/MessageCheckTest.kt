package com.ruko.demo.signals

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File

/** Message check (A5): OTP warnings, the sender filter and the "looks AI-written" hint. */
class MessageCheckTest {
    private val repo: File = generateSequence(File("").absoluteFile) { it.parentFile }
        .first { File(it, "ml/model/artifacts/lure.json").exists() }
    private val artifacts = File(repo, "ml/model/artifacts")
    private val lure = LinearLureClassifier(
        Json { ignoreUnknownKeys = true }.decodeFromString(LureModel.serializer(), File(artifacts, "lure.json").readText()),
    )

    /** A stand-in "AI-written" model that says yes (p = sigmoid(2) = 0.88) to every text. */
    private val alwaysAi = AiTextScorer(
        LureModel("test-ai", ngramRange = listOf(2, 3), classes = listOf("human", "ai"), vocabulary = mapOf("zq" to 0), idf = listOf(1.0), coef = listOf(listOf(0.0)), intercept = listOf(2.0)),
        AiTextMeta("test-ai", threshold = 0.7),
    )

    private val otp = "482915 is your OTP for login. Do not share it with anyone."
    private val longPersonal = "Dear Sir, your parcel is held at customs and an officer will call you today. " +
        "Please keep your phone free and do not tell anyone about this matter."

    @Test
    fun otpIsFoundInEnglishAndHindi() {
        assertTrue(MessageCheck.isOtp(otp))
        assertTrue(MessageCheck.isOtp("Your one-time password is 7731"))
        assertTrue(MessageCheck.isOtp("आपका ओटीपी 482915 है। इसे किसी के साथ साझा न करें।"))
        assertFalse(MessageCheck.isOtp("Your order 123456 has shipped"))
        assertFalse(MessageCheck.isOtp("Please share the OTP when you get it"))
    }

    @Test
    fun otpDuringAnUnknownCallGetsTheFullWarning() {
        val ts = 1_000_000L
        val unknownCall = listOf(CallWindow(ts - 60_000, ts + 60_000, callerKnown = null))
        val noCall = emptyList<CallWindow>()
        val contactCall = listOf(CallWindow(ts - 60_000, ts + 60_000, callerKnown = true))
        val ongoing = listOf(CallWindow(ts - 1, null, callerKnown = null))
        val endedBefore = listOf(CallWindow(ts - 600_000, ts - 300_000, callerKnown = null))

        assertTrue(MessageCheck.check("VM-HDFCBK", otp, ts, lure, null, unknownCall).otpDuringCall)
        assertTrue(MessageCheck.check("VM-HDFCBK", otp, ts, lure, null, ongoing).otpDuringCall)
        assertFalse(MessageCheck.check("VM-HDFCBK", otp, ts, lure, null, noCall).otpDuringCall)
        assertFalse(MessageCheck.check("VM-HDFCBK", otp, ts, lure, null, contactCall).otpDuringCall)
        assertFalse(MessageCheck.check("VM-HDFCBK", otp, ts, lure, null, endedBefore).otpDuringCall)
        // Every OTP still gets "never share this".
        assertTrue(MessageCheck.check("VM-HDFCBK", otp, ts, lure, null, noCall).otp)
    }

    @Test
    fun businessHeadersNeverGetTheAiLabel() {
        assertEquals(SenderKind.BUSINESS, MessageCheck.senderKind("VM-HDFCBK"))
        assertEquals(SenderKind.BUSINESS, MessageCheck.senderKind("AX-ICICIT-S"))
        assertEquals(SenderKind.PERSON, MessageCheck.senderKind("+919876543210"))
        assertNull(MessageCheck.senderKind(" "))

        assertNull(MessageCheck.check("VM-HDFCBK", longPersonal, 0, lure, alwaysAi, emptyList()).aiWritten)
        assertEquals(true, MessageCheck.check("+919876543210", longPersonal, 0, lure, alwaysAi, emptyList()).aiWritten)
    }

    @Test
    fun aiLabelIsUnknownWithoutAModelOrOnShortTexts() {
        assertNull(MessageCheck.check("+919876543210", longPersonal, 0, lure, null, emptyList()).aiWritten)
        assertNull(MessageCheck.check("+919876543210", "Reached home, call you later", 0, lure, alwaysAi, emptyList()).aiWritten)
        assertNull(MessageCheck.check("+919876543210", otp, 0, lure, alwaysAi, emptyList()).aiWritten)
    }

    @Test
    fun scamScriptIsLabelled() {
        val text = "Dear Citizen, this is an official notice from the Cyber Crime Investigation Cell. Your Aadhaar-linked " +
            "number has been associated with a money laundering case. To avoid immediate arrest, you must join a " +
            "confidential video verification within the next 60 minutes. Do not disclose this to anyone."
        val m = MessageCheck.check("+919876543210", text, 0, lure, null, emptyList())
        assertNotNull(m.scamTag)
        assertTrue(m.anyWarning)
        assertFalse(m.preview.contains('\n'))
        assertNull(MessageCheck.check("+919876543210", "Mom, I reached the hostel safely. Will call after dinner.", 0, lure, null, emptyList()).scamTag)
    }

    /** Diwansu's ai_text.json must score the same here as in Python (skipped until it exists). */
    @Test
    fun aiTextModelMatchesPythonVectors() {
        val model = File(artifacts, "ai_text.json")
        val vectorsFile = File(artifacts, "ai_text_vectors.json")
        assumeTrue(model.exists() && vectorsFile.exists())
        val scorer = AiTextScorer.parse(model.readText())
        val vectors = Json.parseToJsonElement(vectorsFile.readText()).jsonObject.getValue("vectors").jsonArray
        for (v in vectors) {
            val o = v.jsonObject
            val text = o.getValue("text").jsonPrimitive.content
            assertEquals(text, o.getValue("probability").jsonPrimitive.double, scorer.probability(text), 1e-6)
        }
    }
}
