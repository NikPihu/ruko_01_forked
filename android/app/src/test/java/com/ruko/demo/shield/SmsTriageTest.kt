package com.ruko.demo.shield

import com.ruko.demo.signals.Flow
import com.ruko.demo.signals.LinearLureClassifier
import com.ruko.demo.signals.LureModel
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test
import java.io.File

/** One decision per SMS: a scam script is warned about and never counted as money (real lure model). */
class SmsTriageTest {
    private val repo: File = generateSequence(File("").absoluteFile) { it.parentFile }
        .first { File(it, "ml/model/artifacts/lure.json").exists() }
    private val lure = LinearLureClassifier(
        Json { ignoreUnknownKeys = true }.decodeFromString(LureModel.serializer(), File(repo, "ml/model/artifacts/lure.json").readText()),
    )
    private val now = 1_800_000_000_000L

    private fun triage(sender: String, body: String, trustNumbers: Boolean = true) =
        SmsTriage.triage(sender, body, now, lure, ai = null, trustNumbers = trustNumbers)

    @Test
    fun aTaskScamThatSaysCreditedIsAScamNotACredit() {
        val v = triage(
            "9123456780",
            "Hello Meena! Congratulations, you have completed 3 of 5 tasks and Rs 900 has been credited to your " +
                "account. To unlock Level 4 and earn up to Rs 8,000 today, please pay a refundable activation fee " +
                "of Rs 2,000 to our UPI ID. Our support team is happy to guide you at every step!",
        )
        assertNotNull(v.scam)
        assertNull(v.txn)
    }

    @Test
    fun genuineBankAlertsStillCountAndAreNotScams() {
        val alerts = listOf(
            "VM-HDFCBK" to "Rs.500.00 credited to A/c XX4821 by UPI from arjun.pandey@okicici. UPI Ref 431289. -HDFC Bank",
            "AX-ICICIB" to "Rs.250.00 credited to A/c XX3210 on 06-11-26 by UPI from rahul.k22@ybl. Ref 6312",
            // The watcher needs the debit to a scammer's UPI ID, so its name must not hide the alert.
            "VM-HDFCBK" to "INR 1,500.00 debited from A/c XX3210 to VPA prime.task.rewards@ybl on 06-11-26",
            "JD-SBIUPI" to "Dear UPI user A/C X3210 debited by 6500.0 on date 06Nov26 trf to TASK DESK Refno 6312",
            "5676780" to "Rs.150.00 credited to A/c XX4821 by UPI from task.rewards.desk@okaxis. UPI Ref 431355. -HDFC Bank",
        )
        for ((sender, body) in alerts) {
            val v = triage(sender, body)
            assertNull("flagged as a scam: $body", v.scam)
            assertNotNull("not counted: $body", v.txn)
        }
        assertEquals(Flow.OUT, triage("VM-HDFCBK", alerts[2].second).txn!!.flow)
    }

    @Test
    fun releaseBuildsDoNotTakeANumberForABank() {
        val v = triage("9876543210", "Rs.500.00 credited to A/c XX4821 by UPI from arjun.pandey@okicici.", trustNumbers = false)
        assertNull(v.txn)
    }

    @Test
    fun anOtpIsNeitherAScamNorMoney() {
        val v = triage("VM-HDFCBK", "123456 is your OTP for UPI payment of Rs 500. Do not share.")
        assertNull(v.scam)
        assertNull(v.txn)
    }
}
