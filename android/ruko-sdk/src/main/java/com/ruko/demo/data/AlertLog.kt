package com.ruko.demo.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** What a phone-side warning was about. Only the kind, the scam type and the time are kept. */
@Serializable
enum class AlertKind {
    @SerialName("scam_message") SCAM_MESSAGE,     // an SMS or chat message matched a scam script
    @SerialName("otp_on_call") OTP_ON_CALL,       // a one-time code arrived during a call
    @SerialName("task_scam") TASK_SCAM,           // the task-scam watcher went ACTIVE
    @SerialName("paid_other_app") PAID_OTHER_APP, // money left through another app during an episode
    @SerialName("ring_confirmed") RING_CONFIRMED,  // the server confirmed the accounts look like a ring
}

/**
 * One warning the phone showed (rule 10: warn, never block). Never the message text, the sender
 * or an amount: the Alerts screen says what kind of warning it was and when (rules 2 and 7).
 */
@Serializable
data class AlertEntry(
    val ts: Long, // epoch millis
    val kind: AlertKind,
    val tag: String? = null, // lure tag for SCAM_MESSAGE, e.g. "task_job"
    val source: String? = null, // "sms" or "chat" for SCAM_MESSAGE
    @SerialName("ai_written") val aiWritten: Boolean = false,
)

/** The alert list as stored (encrypted, alerts.enc): newest first, plus when the user last looked. */
@Serializable
data class AlertLogFile(
    val entries: List<AlertEntry> = emptyList(),
    @SerialName("seen_at") val seenAt: Long = 0,
)

/** Pure rules for the alert list, so they run in plain unit tests. */
object AlertLog {
    const val KEEP_MS = 30L * 24 * 60 * 60_000
    const val MAX = 100
    // The same warning again within this window (a long SMS in parts, a chat that re-posts) is one alert.
    const val REPEAT_MS = 10L * 60_000

    /**
     * Kinds that can arrive twice for one event: a scam SMS in parts or a chat that re-posts, and the
     * server confirming the same ring again. Every task-scam step, payment in another app and OTP on a
     * call is its own event (the watcher already drops a repeat of the same transaction).
     */
    private val MERGE_REPEATS = setOf(AlertKind.SCAM_MESSAGE, AlertKind.RING_CONFIRMED)

    /** The same warning again within [REPEAT_MS]: not a new alert (no new row, no new notification). */
    fun isRepeat(file: AlertLogFile, entry: AlertEntry): Boolean = entry.kind in MERGE_REPEATS && file.entries.any {
        it.kind == entry.kind && it.tag == entry.tag && it.source == entry.source && entry.ts - it.ts in 0..REPEAT_MS
    }

    fun add(file: AlertLogFile, entry: AlertEntry, now: Long = entry.ts): AlertLogFile {
        val entries = if (isRepeat(file, entry)) file.entries else listOf(entry) + file.entries
        return file.copy(entries = trim(entries, now))
    }

    fun trim(entries: List<AlertEntry>, now: Long): List<AlertEntry> =
        entries.filter { now - it.ts <= KEEP_MS }.sortedByDescending { it.ts }.take(MAX)

    fun unseen(file: AlertLogFile): Int = file.entries.count { it.ts > file.seenAt }
}
