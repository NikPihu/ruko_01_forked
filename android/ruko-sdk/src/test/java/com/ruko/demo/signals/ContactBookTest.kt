package com.ruko.demo.signals

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ContactBookTest {

    private val book = setOf("+918714102747", "+916094164582")

    @Test
    fun aContactPaidByMobileNumberIsInContacts() {
        assertTrue(ContactMatch.payeeInContacts(book, "sai.das@okaxis", "+91 87141 02747"))
        assertTrue(ContactMatch.payeeInContacts(book, "sai.das@okaxis", "08714102747"))
    }

    @Test
    fun aMobileStyleUpiIdIsMatchedByItsNumber() {
        assertEquals("+916094164582", ContactMatch.mobileOfUpi("6094164582@okhdfcbank"))
        assertTrue(ContactMatch.payeeInContacts(book, "6094164582@okhdfcbank", null))
        assertNull(ContactMatch.mobileOfUpi("sai.das@okaxis"))
        assertNull(ContactMatch.mobileOfUpi("1234567890@oksbi")) // not an Indian mobile
    }

    @Test
    fun aNameStyleUpiIdTypedByHandIsNotAContact() {
        // The phone cannot see a contact behind it; "no" only makes the payment look riskier.
        assertFalse(ContactMatch.payeeInContacts(book, "secure.settlement.desk@okaxis", null))
        assertFalse(ContactMatch.payeeInContacts(book, "kiran.sinha@paytm", "+917475379466"))
    }

    @Test
    fun theSamePersonSavedTwiceShowsOnceSortedByName() {
        val tidy = ContactMatch.tidy(listOf("Sai Das" to "08714102747", "sai" to "+918714102747", "Arjun" to "6094164582", "Bad" to "123"))
        assertEquals(listOf("Arjun", "Sai Das"), tidy.map { it.name })
        assertEquals(listOf("+916094164582", "+918714102747"), tidy.map { it.mobile })
    }
}
