package com.ruko.demo.net

import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ContractTest {

    @Test
    fun payeeHashMatchesPython() {
        // python -c "import hashlib;print(hashlib.sha256(('meena.mule@okaxis'+'test_salt').encode()).hexdigest())"
        assertEquals(
            "4fdeb717d5a95a4b634a8d96aadb60f1f86ec96dca85fc7464fd1d653240618a",
            payeeHash("  Meena.Mule@OKAXIS ", salt = "test_salt"),
        )
    }

    @Test
    fun optedOutRequestSendsNullContextAndContractKeys() {
        val request = RequestBuilder.build(
            userId = "u_demo_meena",
            upiId = "x@okaxis",
            amountInr = 95000.0,
            typedManually = true,
            context = null,
            ts = "2026-11-07T10:40:00+05:30",
        )
        val json = RukoJson.parseToJsonElement(
            RukoJson.encodeToString(DecideRequest.serializer(), request)
        ).jsonObject

        assertEquals(
            setOf("user_id", "payee_vpa_hash", "amount_inr", "ts", "context", "lure_tags", "payee_typed_manually"),
            json.keys,
        )
        assertEquals(JsonNull, json["context"])
    }

    @Test
    fun contextKeysAreSnakeCase() {
        val json = RukoJson.parseToJsonElement(
            RukoJson.encodeToString(Context.serializer(), Context())
        ).jsonObject
        assertEquals(
            setOf(
                "on_call", "caller_in_contacts", "call_minutes", "remote_access_app",
                "accessibility_on", "sideload_last_24h", "screen_recorded",
            ),
            json.keys,
        )
    }

    @Test
    fun responseIgnoresUnknownFields() {
        val response = RukoJson.decodeFromString(
            DecideResponse.serializer(),
            """{"tier":"T3","reasons":["R1_live_unknown_call"],"message_key":"t3_digital_arrest","extra":1}""",
        )
        assertEquals("T3", response.tier)
        assertEquals("t3_digital_arrest", response.messageKey)
    }

    @Test
    fun timestampIsIstIso8601() {
        assertTrue(Regex("""\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+05:30""").matches(RequestBuilder.nowIst()))
    }
}
