package com.ruko.demo.ui.alerts

import com.ruko.demo.R
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class AlertsTest {

    private val android: File = generateSequence(File("").absoluteFile) { it.parentFile }
        .map { if (File(it, "app/src/main/res").exists()) it else File(it, "android") }
        .first { File(it, "app/src/main/res/values/strings.xml").exists() }

    private fun strings(folder: String): Map<String, String> =
        Regex("""<string name="([^"]+)">(.*?)</string>""")
            .findAll(File(android, "app/src/main/res/$folder/strings.xml").readText())
            .associate { it.groupValues[1] to it.groupValues[2].replace("\\'", "'") }

    private val en = strings("values")
    private val hi = strings("values-hi")

    private fun name(id: Int): String = R.string::class.java.fields.first { it.getInt(null) == id }.name

    // ---------- message keys ----------

    @Test
    fun unknownKeyFallsBackToTheTierGeneric() {
        for (key in listOf("t3_brand_new_playbook", "nonsense", "", null, "T3_DIGITAL_ARREST")) {
            assertEquals("t1_tip_title", name(AlertText.messageTitle(key, "T1")))
            assertEquals("t2_generic_title", name(AlertText.messageTitle(key, "T2")))
            assertEquals("t3_generic_body", name(AlertText.messageBody(key, "T3")))
            assertEquals("t4_review_title", name(AlertText.messageTitle(key, "T4")))
        }
    }

    @Test
    fun everyServerKeyHasItsOwnWords() {
        val serverKeys = listOf("t1_tip", "t2_generic", "t3_generic") +
            AlertText.PLAYBOOKS.flatMap { listOf("t2_$it", "t3_$it") }
        for (key in serverKeys) {
            val tier = key.substringBefore('_').uppercase()
            assertEquals("${key}_title", name(AlertText.messageTitle(key, tier)))
            assertEquals("${key}_body", name(AlertText.messageBody(key, tier)))
        }
    }

    @Test
    fun scamTypeKeepsItsWordsAcrossTiers() {
        // "I know this person" turns the T3 pause into the T2 card: same scam type, T2 words.
        assertEquals("t2_digital_arrest_title", name(AlertText.messageTitle("t3_digital_arrest", "T2")))
        // T4 has one text: the bank is checking. The scam type is shown below it.
        assertEquals("t4_review_title", name(AlertText.messageTitle("t4_digital_arrest", "T4")))
        assertEquals("digital_arrest", AlertText.playbookOf("t4_digital_arrest"))
        assertEquals(null, AlertText.playbookOf("t3_generic"))
    }

    @Test
    fun everyAlertStringIsInEnglishAndHindi() {
        val alertNames = en.keys.filter { Regex("t[1-4]_.*|alert_.*|trusted_contact_sms").matches(it) }
        val needed = AlertText.KEYS.flatMap { listOf("${it}_title", "${it}_body") }
        assertTrue(alertNames.containsAll(needed))
        for (n in alertNames) {
            assertTrue("missing Hindi for $n", n in hi)
            assertTrue("Hindi not translated: $n", hi[n] != en[n])
        }
    }

    @Test
    fun copyNeverShowsTierOrScore() {
        for (n in en.keys.filter { Regex("t[1-4]_.*|alert_.*").matches(it) }) {
            for (text in listOf(en.getValue(n), hi.getValue(n))) {
                assertFalse("$n shows a tier: $text", Regex("\\bT[0-4]\\b").containsMatchIn(text))
                assertFalse("$n shows a score: $text", text.contains("%") && !text.contains("%1\$d") && !text.contains("%1\$s"))
            }
        }
    }

    @Test
    fun appModelsHaveNoScore() {
        val models = File(android, "app/src/main/java/com/ruko/demo/net/Models.kt").readText()
        assertFalse(models.contains("p_scam") || models.contains("pScam"))
    }

    // ---------- screens and timing ----------

    @Test
    fun t1AddsNoScreen() {
        assertEquals(AlertScreen.PIN, screenFor("T0"))
        assertEquals(AlertScreen.PIN, screenFor("T1"))
        assertEquals(AlertScreen.EXPLAIN, screenFor("T2"))
        assertEquals(AlertScreen.PAUSE, screenFor("T3"))
        assertEquals(AlertScreen.REVIEW, screenFor("T4"))
        assertEquals(AlertScreen.UNAVAILABLE, screenFor(null)) // fail open
    }

    @Test
    fun t2SlideIsDisabledForFiveSeconds() {
        val shown = 1_000_000L
        assertFalse(AlertRules.slideEnabled(shown, shown))
        assertFalse(AlertRules.slideEnabled(shown, shown + 4_999))
        assertTrue(AlertRules.slideEnabled(shown, shown + 5_000))
        assertEquals(5, AlertRules.readGateLeftSeconds(shown, shown))
        assertEquals(1, AlertRules.readGateLeftSeconds(shown, shown + 4_500))
        assertEquals(0, AlertRules.readGateLeftSeconds(shown, shown + 9_000))
    }

    @Test
    fun t3PayAnywayIsHiddenUntilThePauseEnds() {
        val decided = 1_700_000_000_000L
        val ends = AlertRules.pauseEndsAt(decided, 30)
        assertEquals(decided + 30 * 60_000L, ends)
        assertFalse(AlertRules.payAnywayVisible(decided, ends))
        assertFalse(AlertRules.payAnywayVisible(ends - 1, ends))
        assertTrue(AlertRules.payAnywayVisible(ends, ends))
        assertEquals(30, AlertRules.minutesLeft(decided, ends))
        assertEquals(1, AlertRules.minutesLeft(ends - 1, ends))
        assertEquals(0, AlertRules.minutesLeft(ends + 5, ends))
    }

    // ---------- trusted person ----------

    @Test
    fun trustedPersonSmsHasNoAmountAndNoPayee() {
        // Meena's payment: ₹95,000 to the demo mule. The builder never receives either.
        val payee = "secure.settlement.desk@okaxis"
        for (template in listOf(en.getValue("trusted_contact_sms"), hi.getValue("trusted_contact_sms"))) {
            val sms = TrustedMessage.body(template, "Meena")
            assertTrue(sms.startsWith("Meena"))
            for (leak in listOf("95000", "95,000", "₹", "Rs", "@", payee, "secure", "okaxis")) {
                assertFalse("SMS leaks '$leak': $sms", sms.contains(leak))
            }
            assertFalse("SMS has a number: $sms", sms.any { it.isDigit() })
        }
    }
}
