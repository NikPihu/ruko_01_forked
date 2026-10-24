package com.ruko.demo.signals

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class BankSmsTest {

    private val now = 1_800_000_000_000L
    private fun hoursAgo(h: Double) = now - (h * 3_600_000).toLong()

    @Test
    fun readsCommonBankAlerts() {
        val credit = BankSms.parse("Rs.250.00 credited to A/c XX3210 on 06-11-26 by UPI from rahul.k22@ybl. Ref 6312", now)!!
        assertEquals(Flow.IN, credit.flow)
        assertEquals(250.0, credit.amount, 0.0)
        assertEquals("rahul.k22@ybl", credit.counterparty)

        val debit = BankSms.parse("INR 1,500.00 debited from A/c XX3210 to VPA prime.task.rewards@ybl on 06-11-26", now)!!
        assertEquals(Flow.OUT, debit.flow)
        assertEquals(1500.0, debit.amount, 0.0)

        val sbi = BankSms.parse("Dear UPI user A/C X3210 debited by 6500.0 on date 06Nov26 trf to TASK DESK Refno 6312", now)!!
        assertEquals(Flow.OUT, sbi.flow)
        assertEquals(6500.0, sbi.amount, 0.0)
        assertNull(sbi.counterparty)

        val hdfc = BankSms.parse("Sent Rs.3000.00 From HDFC Bank A/C x3210 To earn.daily@okicici On 06/11/26", now)!!
        assertEquals(Flow.OUT, hdfc.flow)
        assertEquals("earn.daily@okicici", hdfc.counterparty)
    }

    @Test
    fun ignoresMessagesWhereNoMoneyMoved() {
        assertNull(BankSms.parse("123456 is your OTP for UPI payment of Rs 500. Do not share.", now))
        assertNull(BankSms.parse("Rs 2000 will be debited from your A/c for the EMI on 10 Nov", now))
        assertNull(BankSms.parse("Collect request of Rs 900 from shop@ybl on your UPI app", now))
        assertNull(BankSms.parse("Rs 15 cashback credited to your account", now))
        assertNull(BankSms.parse("Earn Rs 3000 daily by liking videos. Join now", now)) // no bank words
    }

    @Test
    fun onlyBankSenderIdsAreTrusted() {
        assertTrue(BankSms.trustedSender("AX-HDFCBK"))
        assertFalse(BankSms.trustedSender("+919812345670")) // a fake "credited" SMS from a number
        assertTrue(BankSms.trustedSender("9812345670", allowNumbers = true))
        assertFalse(BankSms.trustedSender(null))
    }

    @Test
    fun readsTheSendersNameWhenTheAlertGivesIt() {
        val pnb = BankSms.parse(
            "A/c X3673 credited for INR 30.00 on 21-10-26 16:27:11 by RAHUL SHARMA (rahul@upi) thru UPI. (UPI:629441147556).-PNB", now,
        )!!
        assertEquals(Flow.IN, pnb.flow)
        assertEquals(30.0, pnb.amount, 0.0)
        assertEquals("rahul@upi", pnb.counterparty)
        assertEquals("RAHUL SHARMA", pnb.counterpartyName)

        val after = BankSms.parse("Rs.500.00 credited to A/c XX4821 from arjun.pandey@okicici (ARJUN  PANDEY). Ref 4312", now)!!
        assertEquals("arjun.pandey@okicici", after.counterparty)
        assertEquals("ARJUN PANDEY", after.counterpartyName)

        val out = BankSms.parse("INR 1,500.00 debited from A/c XX3210 to PRIME TASKS (prime.task.rewards@ybl) on 06-11-26", now)!!
        assertEquals(Flow.OUT, out.flow)
        assertEquals("PRIME TASKS", out.counterpartyName)
    }

    @Test
    fun noNameMeansUnknownNotMadeUp() {
        assertNull(BankSms.parse("Rs.250.00 credited to A/c XX3210 on 06-11-26 by UPI from rahul.k22@ybl. Ref 6312", now)!!.counterpartyName)
        // "(UPI)" sits where a name could, but is not one.
        assertNull(BankSms.parse("Rs.250.00 credited to A/c XX3210 from rahul.k22@ybl (UPI). Ref 6312", now)!!.counterpartyName)
        assertEquals("rahul.k22@ybl", BankSms.parse("Rs.250.00 credited to A/c XX3210 from rahul.k22@ybl (UPI). Ref 6312", now)!!.counterparty)
    }
}
