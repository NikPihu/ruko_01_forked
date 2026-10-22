package com.ruko.demo.signals

import android.Manifest.permission.READ_CONTACTS
import android.content.Context
import android.content.pm.PackageManager
import android.provider.ContactsContract
import androidx.core.content.ContextCompat

/** One saved contact with a mobile number. In memory only, never sent anywhere. */
data class SavedContact(val name: String, val mobile: String) // mobile as +91XXXXXXXXXX

/** The matching rules, without Android, so ContactBookTest can run them. */
object ContactMatch {
    private val MOBILE_VPA = Regex("""^([6-9]\d{9})@[a-z]+$""")

    /** The mobile number inside a UPI ID like 9876543210@oksbi, or null when it has none. */
    fun mobileOfUpi(upiId: String): String? =
        MOBILE_VPA.find(upiId.trim().lowercase())?.groupValues?.get(1)?.let { "+91$it" }

    /**
     * Is this payee a saved contact? Yes when the mobile number it is paid by, or the number inside
     * its UPI ID, is in [contacts]. No otherwise: the phone cannot see a contact behind a name-style
     * UPI ID typed by hand, and "no" only ever makes a payment look riskier.
     */
    fun payeeInContacts(contacts: Set<String>, upiId: String, payeeMobile: String?): Boolean {
        val numbers = listOfNotNull(payeeMobile?.let(::toE164), mobileOfUpi(upiId))
        return numbers.any { it in contacts }
    }

    /** Same person saved twice (with and without +91) counts once; sorted by name. */
    fun tidy(raw: List<Pair<String, String>>): List<SavedContact> =
        raw.mapNotNull { (name, number) -> toE164(number)?.let { SavedContact(name.trim().ifEmpty { it }, it) } }
            .distinctBy { it.mobile }
            .sortedBy { it.name.lowercase() }
}

/** The phone's own address book, read with the Contacts permission the call checks already ask for. */
class ContactBook(private val app: Context) {

    fun canRead(): Boolean =
        ContextCompat.checkSelfPermission(app, READ_CONTACTS) == PackageManager.PERMISSION_GRANTED

    /** Contacts with a mobile number; null when they cannot be read (no permission). */
    fun all(): List<SavedContact>? {
        if (!canRead()) return null
        return try {
            val raw = ArrayList<Pair<String, String>>()
            app.contentResolver.query(
                ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
                arrayOf(ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME, ContactsContract.CommonDataKinds.Phone.NUMBER),
                null, null, null,
            )?.use { c ->
                while (c.moveToNext()) raw += (c.getString(0) ?: "") to (c.getString(1) ?: "")
            }
            ContactMatch.tidy(raw)
        } catch (e: SecurityException) {
            null
        }
    }

    /** c2-0.7 `payee_in_contacts`: null when contacts cannot be read (unknown, never "safe"). */
    fun payeeInContacts(upiId: String, payeeMobile: String?): Boolean? =
        all()?.let { book -> ContactMatch.payeeInContacts(book.mapTo(HashSet()) { it.mobile }, upiId, payeeMobile) }
}
