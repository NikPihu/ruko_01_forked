package com.ruko.demo.data

import java.time.DateTimeException
import java.time.LocalDate
import java.time.Period

/** Input checks for sign up. Pure functions, so they run in plain unit tests. */
object Validators {
    private val MOBILE = Regex("^[6-9][0-9]{9}$")
    private val EMAIL = Regex("^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$")
    private val NAME = Regex("^[\\p{L} .']{2,60}$")
    private val IFSC = Regex("^[A-Z]{4}0[A-Z0-9]{6}$")
    private val PAN = Regex("^[A-Z]{5}[0-9]{4}[A-Z]$")
    private val UPI_HANDLE = Regex("^[a-z0-9._-]{3,40}$")
    private val LAST4 = Regex("^[0-9]{4}$")

    fun isMobile(value: String) = MOBILE.matches(value)
    fun isEmail(value: String) = EMAIL.matches(value.trim())
    fun isName(value: String) = NAME.matches(value.trim()) && value.any { it.isLetter() }
    fun isIfsc(value: String) = IFSC.matches(value)
    fun isPan(value: String) = PAN.matches(value)
    fun isUpiHandle(value: String) = UPI_HANDLE.matches(value)
    fun isLast4(value: String) = LAST4.matches(value)

    /** Date of birth from separate day, month and year fields, or null if it is not a real date. */
    fun dateOfBirth(day: String, month: String, year: String): LocalDate? =
        if (year.length != 4) {
            null
        } else {
            try {
                LocalDate.of(year.toInt(), month.toInt(), day.toInt())
            } catch (e: DateTimeException) {
                null
            } catch (e: NumberFormatException) {
                null
            }
        }

    /** Payment accounts here are for adults; also rejects future dates and years before 1900. */
    fun isAdult(dob: LocalDate, today: LocalDate = LocalDate.now()): Boolean =
        dob.year >= 1900 && !dob.isAfter(today) && Period.between(dob, today).years >= 18
}

/** How personal details are shown on screen: never in full. */
object Masks {
    fun mobile(mobile: String) = "+91 ••••••" + mobile.takeLast(4)
    fun pan(pan: String) = "••••••" + pan.takeLast(4)
    fun account(last4: String) = "•••• $last4"
    fun dateOfBirth(isoDate: String) = "••/••/" + isoDate.take(4)
    fun email(email: String): String {
        val at = email.indexOf('@')
        return if (at <= 1) email else email.first() + "•••" + email.substring(at)
    }
}
