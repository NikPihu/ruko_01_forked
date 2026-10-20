package com.ruko.demo.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

class ValidatorsTest {

    @Test
    fun mobileNumbers() {
        assertTrue(Validators.isMobile("9876543210"))
        assertFalse(Validators.isMobile("5876543210")) // Indian mobiles start with 6 to 9
        assertFalse(Validators.isMobile("987654321"))
    }

    @Test
    fun bankAndKycFormats() {
        assertTrue(Validators.isIfsc("SBIN0001234"))
        assertFalse(Validators.isIfsc("SBIN1001234")) // fifth character must be 0
        assertTrue(Validators.isPan("ABCDE1234F"))
        assertFalse(Validators.isPan("ABCD12345F"))
        assertTrue(Validators.isUpiHandle("meena.k_58"))
        assertFalse(Validators.isUpiHandle("me"))
        assertTrue(Validators.isLast4("4321"))
        assertFalse(Validators.isLast4("43a1"))
    }

    @Test
    fun namesAndEmail() {
        assertTrue(Validators.isName("Meena Kulkarni"))
        assertFalse(Validators.isName("M"))
        assertTrue(Validators.isEmail("meena@example.com"))
        assertFalse(Validators.isEmail("meena@example"))
    }

    @Test
    fun dateOfBirthAndAge() {
        val today = LocalDate.of(2026, 10, 20)
        assertNull(Validators.dateOfBirth("31", "02", "1968"))
        assertNull(Validators.dateOfBirth("1", "1", "68"))
        val dob = Validators.dateOfBirth("12", "06", "1968")!!
        assertTrue(Validators.isAdult(dob, today))
        assertFalse(Validators.isAdult(LocalDate.of(2010, 1, 1), today))
        assertFalse(Validators.isAdult(LocalDate.of(1890, 1, 1), today))
    }

    @Test
    fun passcodeHashIsSaltedAndVerifies() {
        val salt = Passcode.newSalt()
        val hash = Passcode.hash("482915", salt)
        assertNotEquals("482915", hash)
        assertTrue(Passcode.matches("482915", salt, hash))
        assertFalse(Passcode.matches("482916", salt, hash))
        assertNotEquals(hash, Passcode.hash("482915", Passcode.newSalt()))
    }

    @Test
    fun masksHideMostOfEachValue() {
        assertEquals("+91 ••••••3210", Masks.mobile("9876543210"))
        assertEquals("••••••234F", Masks.pan("ABCDE1234F"))
        assertEquals("m•••@example.com", Masks.email("meena@example.com"))
        assertEquals("••/••/1968", Masks.dateOfBirth("1968-06-12"))
    }
}
