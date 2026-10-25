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

    /** A stand-in lure model with a fixed answer. */
    private fun fixed(hit: LureHit) = object : LureClassifier {
        override val version = "fixed"
        override fun classify(text: String) = hit
    }

    @Test
    fun unclearIsShownAsBeCarefulNeverAsNoWarning() {
        val unsure = fixed(LureHit(LURE_UNCLEAR, 0.45, top = "kyc"))
        val m = MessageCheck.check("+919876543210", "Your account needs attention, call us", 0, unsure, null, emptyList())
        assertTrue(m.unclear)
        assertNull(m.scamTag) // not a scam label, so no notification and no lure_seen
        assertNull(m.scamConf)
        assertTrue(m.anyWarning)
        assertTrue(m.handles.isEmpty())
        // Leaning to normal is still unclear.
        assertTrue(MessageCheck.check("+919876543210", "ok", 0, fixed(LureHit(LURE_UNCLEAR, 0.55, top = "normal")), null, emptyList()).unclear)
        // An OTP keeps its own label instead.
        assertFalse(MessageCheck.check("VM-HDFCBK", otp, 0, unsure, null, emptyList()).unclear)
        // A decided answer is never unclear.
        val normal = MessageCheck.check("+919876543210", "ok", 0, fixed(LureHit(LURE_NORMAL, 0.9)), null, emptyList())
        assertFalse(normal.unclear)
        assertFalse(normal.anyWarning)
    }

    @Test
    fun otherScamIsAScamScript() {
        val m = MessageCheck.check("+919876543210", "Pay the redelivery fee", 0, fixed(LureHit("other_scam", 0.9)), null, emptyList())
        assertEquals("other_scam", m.scamTag)
        assertEquals(0.9, m.scamConf!!, 0.0)
        assertFalse(m.unclear)
        assertNull(MessageCheck.check("+919876543210", "x", 0, fixed(LureHit("other_scam", 0.59)), null, emptyList()).scamTag)
    }

    /** The ML ai_text.json must score the same here as in Python (skipped until it exists). */
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

    @Test
    fun anOtpIsActedOnOnlyWhenItIsForUpiOrABank() {
        fun purpose(sender: String?, body: String) = MessageCheck.otpPurpose(sender, body)
        // The sender header of a bank or a UPI app decides.
        assertEquals(OtpPurpose.BANK, purpose("VM-HDFCBK", "482915 is your OTP for login. Do not share it."))
        assertEquals(OtpPurpose.BANK, purpose("JD-SBIOTP", "Your OTP is 7731 for the transaction."))
        assertEquals(OtpPurpose.UPI, purpose("AX-PHONPE", "OTP 552901 to verify your device. Do not share."))
        // Otherwise the words.
        assertEquals(OtpPurpose.UPI, purpose("5676780", "Use OTP 482913 to set your UPI PIN. Never share it."))
        assertEquals(OtpPurpose.UPI, purpose("AD-NOTIFY", "OTP 119922 to link your bank account to Google Pay."))
        assertEquals(OtpPurpose.BANK, purpose("5676780", "482913 is your OTP to log in to HDFC Bank NetBanking."))
        assertEquals(OtpPurpose.BANK, purpose("AD-NOTIFY", "OTP 4410 to add a beneficiary to your a/c XX4821."))
        assertEquals(OtpPurpose.BANK, purpose(null, "आपका ओटीपी 482915 है। बैंक खाते से लेनदेन के लिए।"))
        // Orders, deliveries and social apps are not money: "your Instagram account" is not a bank account.
        assertEquals(OtpPurpose.OTHER, purpose("AX-SWIGGY", "Your OTP for order delivery is 4821."))
        assertEquals(OtpPurpose.OTHER, purpose("VK-AMAZON", "482915 is your Amazon OTP. Do not share it."))
        assertEquals(OtpPurpose.OTHER, purpose("JM-INSTAG", "Use 123456 as your Instagram account verification code."))
        assertEquals(OtpPurpose.UNKNOWN, purpose("5676780", "Your OTP is 482915. Do not share it with anyone."))
        assertNull(purpose("VM-HDFCBK", "Rs.500.00 credited to A/c XX4821"))   // not an OTP at all
        assertTrue(OtpPurpose.UPI.forMoney && OtpPurpose.BANK.forMoney)
        assertFalse(OtpPurpose.OTHER.forMoney || OtpPurpose.UNKNOWN.forMoney)
    }

    @Test
    fun aNonMoneyOtpOnACallGetsNoTakeoverWarning() {
        val ts = 1_000_000L
        val call = listOf(CallWindow(ts - 60_000, ts + 60_000, callerKnown = false))
        val swiggy = MessageCheck.check("AX-SWIGGY", "Your OTP for order delivery is 4821.", ts, lure, null, call)
        assertTrue(swiggy.otp)                     // still "never share this"
        assertFalse(swiggy.otpDuringCall)          // but no takeover warning
        assertEquals(OtpPurpose.OTHER, swiggy.otpPurpose)
        val bank = MessageCheck.check("5676780", "Use OTP 482913 to set your UPI PIN.", ts, lure, null, call)
        assertTrue(bank.otpDuringCall)
        assertEquals(OtpPurpose.UPI, bank.otpPurpose)
    }
}
