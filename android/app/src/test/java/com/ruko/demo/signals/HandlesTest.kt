package com.ruko.demo.signals

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** Money handles (c2-0.13): same normalisation and hashing as the server, found in real-looking scams. */
class HandlesTest {
    private val repo: File = generateSequence(File("").absoluteFile) { it.parentFile }
        .first { File(it, "contracts/examples/handle_vectors.json").exists() }

    @Test
    fun matchesTheServerOnTheSharedVectors() {
        val doc = Json.parseToJsonElement(File(repo, "contracts/examples/handle_vectors.json").readText()).jsonObject
        assertEquals(doc.getValue("salt").jsonPrimitive.content, Handles.SALT)
        for (v in doc.getValue("vectors").jsonArray) {
            val o = v.jsonObject
            val kind = o.getValue("kind").jsonPrimitive.content
            val raw = o.getValue("raw").jsonPrimitive.content
            assertEquals("$kind $raw", o.getValue("normalised").jsonPrimitive.contentOrNull, Handles.normalise(kind, raw))
            assertEquals("$kind $raw", o.getValue("wire").jsonPrimitive.contentOrNull, Handles.wireValue(kind, raw))
        }
    }

    @Test
    fun saltIsTheOneInWatchRules() {
        val rules = Json.parseToJsonElement(File(repo, "contracts/watch_rules.json").readText()).jsonObject
        assertEquals(rules.getValue("handle_salt").jsonPrimitive.content, Handles.SALT)
    }

    @Test
    fun findsUpiLinkAndNumberInAnAiStyleMessage() {
        val msg = "Dear valued customer, your KYC verification is pending and your account will be restricted " +
            "today. Kindly pay the Rs 10 verification fee to kyc.refund.desk@ybl or complete it at " +
            "https://www.kyc-update-now.example/verify?id=9. For help call our desk on +91 98123 45670."
        val h = Handles.extract(msg).associate { it.kind to it.value }
        assertEquals("kyc.refund.desk@ybl", h["upi"])
        assertEquals(Handles.wireValue("link", "kyc-update-now.example"), h["link"])
        assertEquals(Handles.wireValue("phone", "9812345670"), h["phone"])
        // Only pseudonyms for the link and the number: nothing readable leaves the phone.
        assertTrue(h.getValue("link").startsWith("sha256:") && h.getValue("phone").startsWith("sha256:"))
    }

    @Test
    fun findsHandlesInHinglish() {
        val msg = "Aapka refund atka hai. Turant 098123-45670 pe call karein aur refund.help24@YBL pe ₹1 bhejein."
        val kinds = Handles.extract(msg).map { it.kind to it.value }.toSet()
        assertTrue(kinds.contains("upi" to "refund.help24@ybl"))
        assertTrue(kinds.contains("phone" to Handles.wireValue("phone", "9812345670")))
    }

    @Test
    fun ordinaryTextIsNotAHandle() {
        // An email, an amount, abbreviations, a name with a dot, an OTP, a date: none of them is a handle.
        val msg = "Write to help@bank.example. Rs.500 credited at 10 a.m. to Mr.Sharma, OTP 482915, on 24-10-2026."
        assertEquals(emptyList<Any>(), Handles.extract(msg))
    }

    @Test
    fun atMostTenHandlesAndNoDuplicates() {
        val many = (1..15).joinToString(" ") { "pay$it.desk@ybl" } + " pay1.desk@ybl"
        val h = Handles.extract(many)
        assertEquals(Handles.MAX, h.size)
        assertEquals(h.size, h.map { it.value }.toSet().size)
    }

    @Test
    fun aFlaggedScamCarriesHandlesButAnOtpDoesNot() {
        val lure = LinearLureClassifier(
            Json { ignoreUnknownKeys = true }.decodeFromString(LureModel.serializer(), File(repo, "ml/model/artifacts/lure.json").readText()),
        )
        val text = "Dear customer, your KYC is pending and your account will be blocked today. " +
            "Update now: pay the verification fee to kyc.refund.desk@ybl to avoid suspension."
        val scam = MessageCheck.check("+919800000000", text, 0, lure, null, emptyList())
        assertTrue("the lure model flags it", scam.scamTag != null)
        assertTrue(scam.handles.any { it.kind == "upi" && it.value == "kyc.refund.desk@ybl" })
        val otp = MessageCheck.check("VM-HDFCBK", "482915 is your OTP. Do not share. Pay kyc.refund.desk@ybl", 0, lure, null, emptyList())
        assertTrue(otp.handles.isEmpty())
    }
}
