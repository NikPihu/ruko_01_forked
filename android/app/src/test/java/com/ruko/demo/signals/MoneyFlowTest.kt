package com.ruko.demo.signals

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MoneyFlowTest {

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
    fun taskScamFlowIsSummarised() {
        val txns = listOf(
            MoneyTxn(hoursAgo(60.0), 150.0, Flow.IN, "a1@ybl", fromSms = true),
            MoneyTxn(hoursAgo(50.0), 200.0, Flow.IN, "b2@ybl", fromSms = true),
            MoneyTxn(hoursAgo(40.0), 300.0, Flow.IN, "c3@ybl", fromSms = true),
            MoneyTxn(hoursAgo(30.0), 1_500.0, Flow.OUT, "task1@ybl"),
            MoneyTxn(hoursAgo(20.0), 3_000.0, Flow.OUT, "task1@ybl"),
            MoneyTxn(hoursAgo(5.0), 6_500.0, Flow.OUT, "task2@ybl"),
            MoneyTxn(hoursAgo(5.0) + 60_000, 6_500.0, Flow.OUT, "task2@ybl", fromSms = true), // same payment
            MoneyTxn(hoursAgo(100.0), 99_000.0, Flow.OUT, "old@ybl"), // outside 72 h
        )
        val m = MoneyFlow.summarise(txns, now, smsRead = true)
        assertEquals(3, m.baitCredits)
        assertEquals(650.0, m.creditsInr!!, 0.0)
        assertEquals(3, m.debits)
        assertEquals(11_000.0, m.debitsInr!!, 0.0)
        assertEquals(2, m.newPayees)
        assertEquals(2, m.escalationSteps)
        assertEquals(6_500.0, m.lastDebitInr!!, 0.0)
    }

    @Test
    fun withoutSmsCreditsAreUnknownNotZero() {
        val m = MoneyFlow.summarise(listOf(MoneyTxn(hoursAgo(2.0), 500.0, Flow.OUT, "x@ybl")), now, smsRead = false)
        assertNull(m.baitCredits)
        assertNull(m.creditsInr)
        assertEquals(1, m.debits)
    }

    @Test
    fun creditsFromPeopleYouPayAreNotBait() {
        val txns = listOf(
            MoneyTxn(hoursAgo(10.0), 200.0, Flow.IN, "friend@ybl", fromSms = true),
            MoneyTxn(hoursAgo(2.0), 400.0, Flow.OUT, "friend@ybl"),
        )
        val m = MoneyFlow.summarise(txns, now, smsRead = true, paidBefore = setOf("friend@ybl"))
        assertEquals(0, m.baitCredits)
        assertEquals(0, m.newPayees)
    }

    @Test
    fun escalationCountsOnlyTheLatestRun() {
        assertEquals(0, MoneyFlow.escalationSteps(emptyList()))
        assertEquals(2, MoneyFlow.escalationSteps(listOf(1_500.0, 3_000.0, 6_500.0)))
        assertEquals(1, MoneyFlow.escalationSteps(listOf(5_000.0, 1_000.0, 2_000.0)))
        assertEquals(0, MoneyFlow.escalationSteps(listOf(1_000.0, 1_200.0))) // 1.2x is not escalation
    }
}
