package com.ruko.demo.shield

import android.content.Context
import android.util.Log
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.ruko.demo.DemoConfig
import com.ruko.demo.data.AccountStore
import com.ruko.demo.data.Consents
import com.ruko.demo.data.SecureStore
import com.ruko.demo.net.ApiClient
import com.ruko.demo.net.CallKind
import com.ruko.demo.net.Handle
import com.ruko.demo.net.RequestBuilder
import com.ruko.demo.net.RukoJson
import com.ruko.demo.net.WatchEvent
import com.ruko.demo.net.WatchKind
import com.ruko.demo.signals.OtpPurpose
import com.ruko.demo.signals.isScamTag
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.io.File
import java.util.UUID
import java.util.concurrent.TimeUnit

/** contracts/watch_rules.json, copied to the app's assets (rule 6); the server reads the same file. */
@Serializable
data class WatchRules(
    val version: String,
    @SerialName("lure_min_conf") val lureMinConf: Double,
    @SerialName("long_call_min") val longCallMin: Double,
    @SerialName("lure_repeat_quiet_min") val lureRepeatQuietMin: Double,
    @SerialName("device_repeat_quiet_hours") val deviceRepeatQuietHours: Double,
    @SerialName("device_recent_hours") val deviceRecentHours: Double,
    @SerialName("max_age_days") val maxAgeDays: Double,
    @SerialName("chat_apps") val chatApps: List<String>,
    @SerialName("handle_salt") val handleSalt: String = "ruko-handles-v1",
    @SerialName("max_handles") val maxHandles: Int = 10,
) {
    companion object {
        const val ASSET = "watch_rules.json"
        private val json = Json { ignoreUnknownKeys = true }

        fun parse(text: String): WatchRules = json.decodeFromString(serializer(), text)

        @Volatile private var cached: WatchRules? = null

        fun load(context: Context): WatchRules = cached ?: parse(
            context.assets.open(ASSET).bufferedReader().use { it.readText() },
        ).also { cached = it }
    }
}

/** What the phone saw, before it becomes a [WatchEvent]. Tags and counts only, never text. */
sealed class Sighting {
    data class Lure(
        val tag: String, val conf: Double, val source: String, val aiWritten: Boolean?,
        val handles: List<Handle> = emptyList(), // c2-0.13: money handles (UPI plain, link/number hashed)
    ) : Sighting()
    data class LongCall(
        val kind: CallKind, val minutes: Double, val callerKnown: Boolean?,
        val callerHash: String? = null, // c2-0.15: the number's pseudonym, only for a non-contact SIM caller
    ) : Sighting()
    /**
     * c2-0.15: a one-time code for UPI or a bank ([purpose]) arrived during a call; [kind] null when
     * the call type was not seen. An OTP for anything else is never reported.
     */
    data class OtpOnCall(
        val kind: CallKind?, val callerKnown: Boolean?, val callerHash: String? = null,
        val purpose: OtpPurpose = OtpPurpose.UNKNOWN,
    ) : Sighting()
    data class RemoteApp(val installedMinAgo: Double?) : Sighting()
    data class Sideload(val within24h: Boolean?) : Sighting()
}

/** Encrypted queue of early warnings, plus when each kind was last queued (to keep quiet after). */
@Serializable
data class WatchState(
    val pending: List<String> = emptyList(),
    @SerialName("last_sent") val lastSent: Map<String, Long> = emptyMap(),
)

/**
 * The rules for early warnings, kept free of Android so they can be tested. A sighting becomes an
 * event only past its threshold, and the same thing is not repeated inside its quiet period.
 */
object WatchPolicy {
    /** The event and its quiet key, or null when nothing should be sent. */
    fun event(s: Sighting, rules: WatchRules, now: Long, lastSent: Map<String, Long>, id: String = UUID.randomUUID().toString()): Pair<WatchEvent, String>? {
        val ts = RequestBuilder.istIso(now)
        val (event, key, quietMs) = when (s) {
            is Sighting.Lure -> {
                // Only scam tags: never normal, never unclear (lure-0.2: no class reached 0.6).
                if (!isScamTag(s.tag) || s.conf < rules.lureMinConf) return null
                // The same scam type is quiet for a while, but a message with new money handles (a new
                // UPI ID, link or number) is reported: that is what the server counts across phones.
                val handleKey = s.handles.map { it.value }.sorted().joinToString("|").takeIf { it.isNotEmpty() }
                Triple(
                    WatchEvent(
                        id, DemoConfig.USER_ID, WatchKind.LURE_SEEN, ts, lureTag = s.tag, lureConf = round2(s.conf),
                        source = s.source, aiWritten = s.aiWritten, handles = s.handles.take(rules.maxHandles).ifEmpty { null },
                    ),
                    "lure:${s.tag}" + (handleKey?.let { ":" + it.hashCode() } ?: ""), minutes(rules.lureRepeatQuietMin),
                )
            }
            is Sighting.LongCall -> {
                // Same "unknown" as the server's tracker: not a contact, or a VoIP caller nobody knows.
                val unknown = s.callerKnown == false || (s.callerKnown == null && s.kind == CallKind.VOIP)
                if (!unknown || s.minutes < rules.longCallMin) return null
                Triple(
                    WatchEvent(
                        id, DemoConfig.USER_ID, WatchKind.LONG_UNKNOWN_CALL, ts, callKind = s.kind, callMinutes = round1(s.minutes),
                        callerHash = s.callerHash,
                    ),
                    "call", 0L, // every long call counts
                )
            }
            is Sighting.OtpOnCall -> {
                // Only an OTP for UPI or a bank; a contact asking for the code is not this warning;
                // an unseen caller is not safe (rule 1).
                if (!s.purpose.forMoney || s.callerKnown == true) return null
                Triple(
                    WatchEvent(
                        id, DemoConfig.USER_ID, WatchKind.OTP_DURING_CALL, ts, callKind = s.kind, callerHash = s.callerHash,
                        otpPurpose = s.purpose.wire,
                    ),
                    "otp", 0L, // every OTP on a call counts
                )
            }
            is Sighting.RemoteApp -> {
                val recent = s.installedMinAgo ?: return null
                if (recent > rules.deviceRecentHours * 60) return null
                Triple(WatchEvent(id, DemoConfig.USER_ID, WatchKind.REMOTE_ACCESS_ON, ts), "remote", hours(rules.deviceRepeatQuietHours))
            }
            is Sighting.Sideload -> {
                if (s.within24h != true) return null
                Triple(WatchEvent(id, DemoConfig.USER_ID, WatchKind.SIDELOAD, ts), "sideload", hours(rules.deviceRepeatQuietHours))
            }
        }
        val last = lastSent[key]
        if (last != null && now - last < quietMs) return null
        return event to key
    }

    /** Which consent a sighting also needs, on top of "Early warnings". */
    fun allowed(s: Sighting, c: Consents): Boolean = c.earlyWarnings && when (s) {
        is Sighting.Lure -> if (s.source == "sms") c.smsLure else c.chatLure
        is Sighting.LongCall -> c.callSignals
        is Sighting.OtpOnCall -> c.callSignals && c.smsLure
        is Sighting.RemoteApp, is Sighting.Sideload -> c.appChecks
    }

    private fun minutes(m: Double) = (m * 60_000).toLong()
    private fun hours(h: Double) = (h * 3_600_000).toLong()
    private fun round1(x: Double) = kotlin.math.round(x * 10) / 10
    private fun round2(x: Double) = kotlin.math.round(x * 100) / 100
}

/**
 * Early warnings to the server (POST /v1/watch, c2-0.9), only with "Early warnings" on. Events
 * wait encrypted and go out through WorkManager when there is a network, like episode events;
 * the server ignores repeated event_ids, so retries are safe. Unsent events expire after a week.
 */
object WatchSender {
    const val WORK = "watch_events"
    private const val FILE = "watch.json"
    private const val TAG = "WatchSender"
    private val LOCK = Any()

    fun report(context: Context, sighting: Sighting, now: Long = System.currentTimeMillis()) {
        try {
            val consents = AccountStore(context).loadConsents()
            if (!WatchPolicy.allowed(sighting, consents)) return
            val rules = WatchRules.load(context)
            val queued = update(context) { st ->
                val (event, key) = WatchPolicy.event(sighting, rules, now, st.lastSent) ?: return@update st
                st.copy(pending = st.pending + RukoJson.encodeToString(WatchEvent.serializer(), event), lastSent = st.lastSent + (key to now))
            }
            if (queued.pending.isNotEmpty()) schedule(context)
        } catch (e: Exception) {
            Log.w(TAG, "early warning not queued", e)
        }
    }

    /** Switching "Early warnings" off deletes anything still waiting. */
    fun clear(context: Context) {
        synchronized(LOCK) { store(context).delete(FILE) }
        WorkManager.getInstance(context).cancelUniqueWork(WORK)
    }

    private fun schedule(context: Context) {
        val request = OneTimeWorkRequestBuilder<WatchSendWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(WORK, ExistingWorkPolicy.KEEP, request)
    }

    /** Send in order; stop at the first failure so WorkManager retries later. */
    suspend fun flush(context: Context): Boolean = withContext(Dispatchers.IO) {
        if (!AccountStore(context).loadConsents().earlyWarnings) {
            clear(context)
            return@withContext true
        }
        val maxAgeMs = (WatchRules.load(context).maxAgeDays * 86_400_000).toLong()
        for (raw in update(context) { it }.pending) {
            val event = runCatching { RukoJson.decodeFromString(WatchEvent.serializer(), raw) }.getOrNull()
            val tooOld = event == null || System.currentTimeMillis() - java.time.OffsetDateTime.parse(event.ts).toInstant().toEpochMilli() > maxAgeMs
            if (!tooOld) {
                try {
                    ApiClient.events.watch(event!!)
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    Log.w(TAG, "early warning not sent, will retry", e)
                    return@withContext false
                }
            }
            update(context) { it.copy(pending = it.pending - raw) }
        }
        true
    }

    private fun update(context: Context, change: (WatchState) -> WatchState): WatchState = synchronized(LOCK) {
        val s = store(context)
        val current = runCatching { s.read(FILE)?.let { RukoJson.decodeFromString(WatchState.serializer(), it.decodeToString()) } }.getOrNull() ?: WatchState()
        val next = change(current)
        if (next != current) s.write(FILE, RukoJson.encodeToString(WatchState.serializer(), next).encodeToByteArray())
        next
    }

    private fun store(context: Context) = SecureStore(File(context.noBackupFilesDir, "secure"))
}

/** WorkManager job for [WatchSender.flush]: needs a network, retries with exponential backoff. */
class WatchSendWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result = if (WatchSender.flush(applicationContext)) Result.success() else Result.retry()
}
