package com.ruko.demo.data

import android.content.Context
import android.util.Log
import com.ruko.demo.signals.MoneyTxn
import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json
import java.io.File
import java.io.IOException
import java.security.GeneralSecurityException

/**
 * The account details a payment app needs, kept only on this phone. None of this is ever
 * sent to the Scam Shield server: the risk API only gets the hashed request in net/.
 */
@Serializable
data class UserProfile(
    @SerialName("local_id") val localId: String,
    @SerialName("full_name") val fullName: String,
    val mobile: String, // 10 digits, checked with an OTP at sign up
    val email: String,
    @SerialName("date_of_birth") val dateOfBirth: String, // yyyy-MM-dd
    val language: String, // "en" or "hi"
    @SerialName("bank_name") val bankName: String,
    @SerialName("account_last4") val accountLast4: String, // never the full account number
    val ifsc: String,
    @SerialName("upi_id") val upiId: String,
    val pan: String? = null, // optional KYC, only ever shown masked
    @SerialName("trusted_name") val trustedName: String? = null,
    @SerialName("trusted_mobile") val trustedMobile: String? = null,
    @SerialName("passcode_salt") val passcodeSalt: String,
    @SerialName("passcode_hash") val passcodeHash: String, // PBKDF2, never the passcode itself
    @SerialName("created_at") val createdAt: String,
) {
    val firstName: String get() = fullName.trim().substringBefore(' ')
}

/** The three Scam Shield switches from the first run screen, plus the storage agreement. */
@Serializable
data class Consents(
    @SerialName("call_signals") val callSignals: Boolean = true,
    @SerialName("app_checks") val appChecks: Boolean = true,
    @SerialName("sms_lure") val smsLure: Boolean = false, // off by default
    // Background task-scam watcher (bank SMS alerts); needs SMS checks. Off by default.
    @SerialName("money_watch") val moneyWatch: Boolean = false,
    // Send the accounts in a suspicious episode to the server (c2-0.4). Off by default.
    @SerialName("share_accounts") val shareAccounts: Boolean = false,
    // How the Pay screen is used (typing rhythm, paste, app switches), counts only (c2-0.5). On by default.
    @SerialName("session_signals") val sessionSignals: Boolean = true,
    @SerialName("storage_agreed") val storageAgreed: Boolean = false,
    @SerialName("agreed_at") val agreedAt: String? = null,
)

class AccountStore(context: Context) {

    private val store = SecureStore(File(context.noBackupFilesDir, "secure"))
    private val json = Json { ignoreUnknownKeys = true }

    fun loadProfile(): UserProfile? = read(PROFILE_FILE, UserProfile.serializer())

    fun saveProfile(profile: UserProfile) = write(PROFILE_FILE, UserProfile.serializer(), profile)

    fun loadConsents(): Consents = read(CONSENTS_FILE, Consents.serializer()) ?: Consents()

    fun saveConsents(consents: Consents) = write(CONSENTS_FILE, Consents.serializer(), consents)

    /** UPI IDs paid before, newest first, so a repeat payment is not "typed by hand". */
    fun loadRecentPayees(): List<String> = read(PAYEES_FILE, ListSerializer(String.serializer())) ?: emptyList()

    fun saveRecentPayees(payees: List<String>) = write(PAYEES_FILE, ListSerializer(String.serializer()), payees)

    /** This app's own payments from the last 30 days, for the task scam money flow. */
    fun loadPayments(): List<MoneyTxn> = read(PAYMENTS_FILE, ListSerializer(MoneyTxn.serializer())) ?: emptyList()

    fun savePayments(payments: List<MoneyTxn>) = write(PAYMENTS_FILE, ListSerializer(MoneyTxn.serializer()), payments)

    /** This user's usual typing rhythm: median seconds between amount digits, last 10 payments. */
    fun loadTypingGaps(): List<Double> = read(TYPING_FILE, ListSerializer(Double.serializer())) ?: emptyList()

    fun saveTypingGaps(gaps: List<Double>) = write(TYPING_FILE, ListSerializer(Double.serializer()), gaps)

    /** Every payment started in this app (90 days, at most 500), with its payment id and outcome. */
    fun loadHistory(): List<PaymentRecord> = read(HISTORY_FILE, ListSerializer(PaymentRecord.serializer())) ?: emptyList()

    fun saveHistory(history: List<PaymentRecord>) = write(HISTORY_FILE, ListSerializer(PaymentRecord.serializer()), history)

    /** Right to erasure: remove the files and the key that could decrypt any copy of them. */
    fun deleteAll() {
        store.delete(PROFILE_FILE)
        store.delete(HISTORY_FILE)
        store.delete(CONSENTS_FILE)
        store.delete(PAYEES_FILE)
        store.delete(PAYMENTS_FILE)
        store.delete(TYPING_FILE)
        store.deleteKey()
    }

    private fun <T> read(name: String, serializer: KSerializer<T>): T? = try {
        store.read(name)?.let { json.decodeFromString(serializer, it.decodeToString()) }
    } catch (e: GeneralSecurityException) {
        // The key is gone or the file was tampered with; treat it as no account.
        Log.w(TAG, "could not decrypt $name", e)
        null
    } catch (e: IOException) {
        Log.w(TAG, "could not read $name", e)
        null
    } catch (e: SerializationException) {
        Log.w(TAG, "could not parse $name", e)
        null
    }

    private fun <T> write(name: String, serializer: KSerializer<T>, value: T) =
        store.write(name, json.encodeToString(serializer, value).encodeToByteArray())

    private companion object {
        const val TAG = "AccountStore"
        const val PROFILE_FILE = "profile.enc"
        const val CONSENTS_FILE = "consents.enc"
        const val PAYEES_FILE = "recent_payees.enc"
        const val PAYMENTS_FILE = "payments.enc"
        const val TYPING_FILE = "typing.enc"
        const val HISTORY_FILE = "history.enc"
    }
}
