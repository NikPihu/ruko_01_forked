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
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * "Message check" (A5): labels for the user's own SMS, worked out on the phone. Nothing here is
 * sent anywhere; the labels are hints and never change a payment's tier (rules 2, 5, 10).
 *
 * - Scam script: the lure model (`lure.json`), same send threshold as the payment check.
 * - Looks AI-written: Diwansu's `ai_text.json`, only for personal or unregistered senders and long
 *   enough texts. Until the model file exists the label is unknown (null) and hidden.
 * - OTP: every one-time code gets "never share this"; one that arrives during a call with someone
 *   not known to be a contact gets the full warning.
 */
object MessageCheck {
    /** AI-text detection is unreliable on short texts, so shorter messages are not judged. */
    const val AI_MIN_WORDS = 12

    private val OTP_WORDS = Regex(
        "(?i)\\b(otp|one[ -]?time[ -]?(password|passcode|code|pin)|verification code|security code|login code|auth(entication)? code)\\b|ओटीपी|वन टाइम पासवर्ड|सत्यापन कोड",
    )
    private val CODE = Regex("(?<!\\d)\\d{4,8}(?!\\d)")

    /** Registered business headers (e.g. `VM-HDFCBK`, `HDFCBK`) contain letters; people have numbers. */
    fun senderKind(sender: String?): SenderKind? {
        val s = sender?.trim().orEmpty()
        if (s.isEmpty()) return null
        return if (s.any(Char::isLetter)) SenderKind.BUSINESS else SenderKind.PERSON
    }

    fun isOtp(body: String): Boolean = OTP_WORDS.containsMatchIn(body) && CODE.containsMatchIn(body)

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
        val otp = isOtp(body)
        val hit = lure.classify(body)
        val scamTag = hit.tag.takeIf { it != "normal" && hit.conf >= LURE_SEND_THRESHOLD }
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
            otpDuringCall = otp && duringUnknownCall(ts, calls),
        )
    }

    private const val PREVIEW_CHARS = 140
}

enum class SenderKind { BUSINESS, PERSON }

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
) {
    val anyWarning: Boolean get() = scamTag != null || aiWritten == true || otp
}

/** `ai_text.json` header: the version, the recommended threshold and which class means "AI". */
@Serializable
data class AiTextMeta(
    val version: String,
    val threshold: Double = 0.5,
    @SerialName("positive_class") val positiveClass: String = "ai",
)

/** Diwansu's "looks AI-written" model: the same TF-IDF + logistic regression format as `lure.json`. */
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
