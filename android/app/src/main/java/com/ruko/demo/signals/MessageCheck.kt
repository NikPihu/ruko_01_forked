package com.ruko.demo.signals

import android.Manifest.permission.READ_CALL_LOG
import android.Manifest.permission.READ_PHONE_STATE
import android.Manifest.permission.READ_SMS
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioManager
import android.provider.CallLog
import android.provider.Telephony
import android.telephony.TelephonyManager
import android.util.Log
import androidx.core.content.ContextCompat
import com.ruko.demo.net.Handle
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * "Message check" (A5): labels for the user's own SMS, worked out on the phone. Nothing here is
 * sent anywhere; the labels are hints and never change a payment's tier (rules 2, 5, 10).
 *
 * - Scam script: the lure model (`lure.json`), same send threshold as the payment check; any scam
 *   class counts, `other_scam` too.
 * - Couldn't tell: no class of the lure model reached 0.6 (`unclear`, lure-0.2). Shown as "be
 *   careful", never as "no warning" (rule 1), and never sent or notified.
 * - Looks AI-written: the ML `ai_text.json`, only for personal or unregistered senders and long
 *   enough texts. Until the model file exists the label is unknown (null) and hidden.
 * - OTP: every one-time code gets "never share this". What it is for is worked out from the sender
 *   and the words ([otpPurpose]); only a UPI or bank OTP that arrives during a call with someone not
 *   known to be a contact gets the full warning (and the c2-0.15 early warning). An OTP for an
 *   order, a delivery or a social app on a call is not acted on.
 */
object MessageCheck {
    /** AI-text detection is unreliable on short texts, so shorter messages are not judged. */
    const val AI_MIN_WORDS = 12

    private val OTP_WORDS = Regex(
        "(?i)\\b(otp|one[ -]?time[ -]?(password|passcode|code|pin)|verification code|security code|login code|auth(entication)? code)\\b|ओटीपी|वन टाइम पासवर्ड|सत्यापन कोड",
    )
    private val CODE = Regex("(?<!\\d)\\d{4,8}(?!\\d)")

    // What an OTP is for (c2-0.15). The sender header first (`VM-HDFCBK`, `AX-PHONPE`), then the words.
    private val UPI_SENDER = Regex("(?i)(PHONPE|PHNPE|PAYTM|GPAY|GOOGLEPAY|BHIM|NPCI|AMZPAY|MOBKWK|CREDIN)")
    private val BANK_SENDER = Regex(
        "(?i)(BK|BNK|BANK|SBI|HDFC|ICICI|AXIS|KOTAK|PNB|CANARA|IDFC|INDUS|YESB|UNIONB|BOBTXN|BOIIND|FEDBNK|RBLBNK|IOB|UCOBNK)",
    )
    private val UPI_WORDS = Regex(
        "(?i)\\b(upi|bhim|vpa|mpin|google ?pay|gpay|phone ?pe|paytm|amazon ?pay|mobikwik|collect request)\\b|यूपीआई",
    )
    private val OTHER_WORDS = Regex(
        "(?i)\\b(order|orders|delivery|deliver|parcel|swiggy|zomato|amazon|flipkart|myntra|meesho|uber|ola|rapido|zepto|blinkit|" +
            "whatsapp|instagram|facebook|telegram|snapchat|gmail|google account|microsoft|netflix|hotstar|dream11|irctc|aadhaar|digilocker)\\b",
    )
    private val BANK_WORDS = Regex(
        "(?i)\\b(bank|banking|net ?banking|internet banking|a/?c|beneficiary|payee|debit card|credit card|card ending|txn|" +
            "transaction|neft|imps|rtgs|fund transfer|withdrawal|atm)\\b|बैंक|खाता|लेनदेन",
    )

    /** Registered business headers (e.g. `VM-HDFCBK`, `HDFCBK`) contain letters; people have numbers. */
    fun senderKind(sender: String?): SenderKind? {
        val s = sender?.trim().orEmpty()
        if (s.isEmpty()) return null
        return if (s.any(Char::isLetter)) SenderKind.BUSINESS else SenderKind.PERSON
    }

    fun isOtp(body: String): Boolean = OTP_WORDS.containsMatchIn(body) && CODE.containsMatchIn(body)

    /**
     * What a one-time code is for, or null when [body] is not an OTP. A bank's or a UPI app's sender
     * header decides; otherwise UPI words, then other services (an order, a delivery, a social app:
     * "your Instagram account" is not a bank account), then bank words. No match: [OtpPurpose.UNKNOWN].
     */
    fun otpPurpose(sender: String?, body: String): OtpPurpose? {
        if (!isOtp(body)) return null
        val header = sender?.trim().orEmpty().takeIf { senderKind(it) == SenderKind.BUSINESS }?.substringAfter('-').orEmpty()
        return when {
            header.isNotEmpty() && UPI_SENDER.containsMatchIn(header) -> OtpPurpose.UPI
            header.isNotEmpty() && BANK_SENDER.containsMatchIn(header) -> OtpPurpose.BANK
            UPI_WORDS.containsMatchIn(body) -> OtpPurpose.UPI
            OTHER_WORDS.containsMatchIn(body) -> OtpPurpose.OTHER
            BANK_WORDS.containsMatchIn(body) -> OtpPurpose.BANK
            else -> OtpPurpose.UNKNOWN
        }
    }

    /** A call was going on at [ts] with someone not known to be a contact (unknown counts, rule 1). */
    fun duringUnknownCall(ts: Long, calls: List<CallWindow>): Boolean =
        calls.any { ts >= it.startMs && ts <= (it.endMs ?: Long.MAX_VALUE) && it.callerKnown != true }

    fun check(
        sender: String?,
        body: String,
        ts: Long,
        lure: LureClassifier,
        ai: AiTextScorer?,
        calls: List<CallWindow>,
        fromPerson: Boolean? = null, // known from where the message came from (a chat app); else from the sender
    ): MessageLabel {
        val purpose = otpPurpose(sender, body)
        val otp = purpose != null
        val hit = lure.classify(body)
        val scamTag = hit.tag.takeIf { hit.scam }
        val words = body.trim().split(Regex("\\s+")).count { it.isNotEmpty() }
        val aiWritten = when {
            ai == null -> null // no model yet: unknown, the label stays hidden
            otp || (fromPerson ?: (senderKind(sender) == SenderKind.PERSON)) != true -> null // business headers are machine-written anyway
            words < AI_MIN_WORDS -> null
            else -> ai.probability(body) >= ai.threshold
        }
        return MessageLabel(
            ts = ts,
            sender = sender?.trim().orEmpty(),
            preview = body.trim().replace(Regex("\\s+"), " ").take(PREVIEW_CHARS),
            scamTag = scamTag,
            scamConf = hit.conf.takeIf { scamTag != null },
            aiWritten = aiWritten,
            otp = otp,
            otpPurpose = purpose,
            // Only a UPI or bank OTP on an unknown call is a takeover warning (c2-0.15).
            otpDuringCall = purpose?.forMoney == true && duringUnknownCall(ts, calls),
            // An OTP is known for what it is and keeps its own warning.
            unclear = hit.unclear && !otp,
            // Money handles only for a message flagged as a scam (c2-0.13); never for an OTP.
            handles = if (scamTag != null && !otp) Handles.extract(body) else emptyList(),
        )
    }

    private const val PREVIEW_CHARS = 140
}

enum class SenderKind { BUSINESS, PERSON }

/** What a one-time code is for (c2-0.15). Only [UPI] and [BANK] are acted on; [wire] is what is sent. */
enum class OtpPurpose(val wire: String) {
    UPI("upi"), BANK("bank"), OTHER("other"), UNKNOWN("unknown");

    val forMoney: Boolean get() = this == UPI || this == BANK
}

/** A call, from the call log or going on now ([endMs] null). [callerKnown] null: not known. */
data class CallWindow(val startMs: Long, val endMs: Long?, val callerKnown: Boolean?)

/** What the Message check screen shows for one SMS. Stays on the phone. */
data class MessageLabel(
    val ts: Long,
    val sender: String,
    val preview: String,
    val scamTag: String?,
    val scamConf: Double?,
    val aiWritten: Boolean?,
    val otp: Boolean,
    val otpDuringCall: Boolean,
    val handles: List<Handle> = emptyList(), // c2-0.13: UPI / link / number pseudonyms, never the text
    val unclear: Boolean = false, // lure-0.2: the model could not tell; "be careful", never "no warning"
    val otpPurpose: OtpPurpose? = null, // c2-0.15: what the OTP is for; null when it is not an OTP
) {
    val anyWarning: Boolean get() = scamTag != null || aiWritten == true || otp || unclear
}

/** `ai_text.json` header: the version, the recommended threshold and which class means "AI". */
@Serializable
data class AiTextMeta(
    val version: String,
    val threshold: Double = 0.5,
    @SerialName("positive_class") val positiveClass: String = "ai",
)

/** The "looks AI-written" model (ml/): the same TF-IDF + logistic regression format as `lure.json`. */
class AiTextScorer(private val model: LureModel, meta: AiTextMeta) {
    val version: String = meta.version
    val threshold: Double = meta.threshold
    private val linear = LinearLureClassifier(model)
    private val positive = model.classes.indexOf(meta.positiveClass).takeIf { it >= 0 } ?: (model.classes.size - 1)

    fun probability(text: String): Double = linear.probabilities(text)[positive]

    companion object {
        private val json = Json { ignoreUnknownKeys = true }

        fun parse(text: String): AiTextScorer =
            AiTextScorer(json.decodeFromString(LureModel.serializer(), text), json.decodeFromString(AiTextMeta.serializer(), text))
    }
}

/** Reads the phone's SMS and calls for the Message check screen and the live OTP warning. */
object MessageScan {
    const val AI_TEXT_ASSET = "ai_text.json"
    private const val WINDOW_MS = 72 * 60 * 60_000L
    private const val MAX_MESSAGES = 50

    /** Null until `ai_text.json` is in the app's assets. */
    fun loadAiText(context: Context): AiTextScorer? = try {
        AiTextScorer.parse(context.assets.open(AI_TEXT_ASSET).bufferedReader().use { it.readText() })
    } catch (e: java.io.FileNotFoundException) {
        null
    } catch (e: Exception) {
        Log.w("MessageScan", "bad $AI_TEXT_ASSET, no AI-written label", e)
        null
    }

    /** Null without the SMS permission: nothing can be checked. */
    fun scan(context: Context, lure: LureClassifier, ai: AiTextScorer?, now: Long): List<MessageLabel>? {
        if (!granted(context, READ_SMS)) return null
        val calls = recentCalls(context, now) + listOfNotNull(callNow(context, now))
        val out = ArrayList<MessageLabel>()
        try {
            context.contentResolver.query(
                Telephony.Sms.Inbox.CONTENT_URI,
                arrayOf(Telephony.Sms.BODY, Telephony.Sms.DATE, Telephony.Sms.ADDRESS),
                "${Telephony.Sms.DATE} >= ?",
                arrayOf((now - WINDOW_MS).toString()),
                "${Telephony.Sms.DATE} DESC",
            )?.use { c ->
                while (c.moveToNext() && out.size < MAX_MESSAGES) {
                    val body = c.getString(0) ?: continue
                    out += MessageCheck.check(c.getString(2), body, c.getLong(1), lure, ai, calls)
                }
            }
        } catch (e: SecurityException) {
            return null
        }
        return out
    }

    /** Calls in the call log over the same window (SIM calls only; VoIP apps do not log here). */
    private fun recentCalls(context: Context, now: Long): List<CallWindow> {
        if (!granted(context, READ_CALL_LOG)) return emptyList()
        val out = ArrayList<CallWindow>()
        try {
            context.contentResolver.query(
                CallLog.Calls.CONTENT_URI,
                arrayOf(CallLog.Calls.DATE, CallLog.Calls.DURATION, CallLog.Calls.CACHED_NAME),
                "${CallLog.Calls.DATE} >= ? AND ${CallLog.Calls.DURATION} > 0",
                arrayOf((now - WINDOW_MS).toString()),
                null,
            )?.use { c ->
                while (c.moveToNext()) {
                    val start = c.getLong(0)
                    // A saved name means a contact; no name is "not known", never "safe".
                    val known = if (!c.getString(2).isNullOrBlank()) true else null
                    out += CallWindow(start, start + c.getLong(1) * 1000L, known)
                }
            }
        } catch (e: SecurityException) {
            return emptyList()
        }
        return out
    }

    /** A call going on right now (SIM or VoIP); who it is with is not known here. */
    fun callNow(context: Context, now: Long): CallWindow? {
        val audio = context.getSystemService(AudioManager::class.java)
        val voip = audio?.mode == AudioManager.MODE_IN_COMMUNICATION
        val sim = granted(context, READ_PHONE_STATE) && try {
            @Suppress("DEPRECATION")
            context.getSystemService(TelephonyManager::class.java)?.callState == TelephonyManager.CALL_STATE_OFFHOOK
        } catch (e: SecurityException) {
            false
        }
        return if (voip || sim || audio?.mode == AudioManager.MODE_IN_CALL) CallWindow(now - 1, null, null) else null
    }

    private fun granted(context: Context, p: String) = ContextCompat.checkSelfPermission(context, p) == PackageManager.PERMISSION_GRANTED
}
