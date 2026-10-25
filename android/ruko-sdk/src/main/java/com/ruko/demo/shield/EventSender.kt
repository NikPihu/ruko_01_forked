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
import com.ruko.sdk.Ruko
import com.ruko.demo.data.AccountStore
import com.ruko.demo.data.Consents
import com.ruko.demo.net.ApiClient
import com.ruko.demo.net.EpisodeAccount
import com.ruko.demo.net.EpisodeEvent
import com.ruko.demo.net.EpisodeSignal
import com.ruko.demo.net.RequestBuilder
import com.ruko.demo.net.RukoJson
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.OffsetDateTime
import java.util.UUID
import java.util.concurrent.TimeUnit

/**
 * Episode events to the server (contract c2-0.4, docs/task-scam-watcher.md §8.4 to 8.6).
 *
 * Only with "Share suspicious accounts" on. One event per state change, with at most 10 of the
 * episode's own accounts; never the full history or any SMS text. Events wait encrypted in
 * EpisodeStore and go out through WorkManager with a network constraint and exponential backoff;
 * the server ignores repeated event_ids, so retries are safe. Undelivered events expire after 7 days.
 */
object EventSender {
    const val WORK = "shield_events"
    const val MAX_ACCOUNTS = 10
    private const val MAX_AGE_MS = 7 * 86_400_000L
    private const val TAG = "EventSender"

    /** Queue one event per transition. With sharing off nothing is queued and the queue is emptied. */
    fun queue(
        data: ShieldData,
        transitions: List<ShieldEngine.Transition>,
        consents: Consents,
        rules: EpisodeRules,
        smsRead: Boolean,
        now: Long,
    ): ShieldData {
        if (!consents.shareAccounts || !consents.moneyWatch) return data.copy(pending = emptyList())
        val fresh = data.pending.filter { p -> decode(p)?.let { now - it.second <= MAX_AGE_MS } ?: false }
        if (transitions.isEmpty()) return data.copy(pending = fresh)
        val tracker = EpisodeTracker(rules, smsRead, data.watcher)
        val summary = tracker.summary(now)
        val events = transitions.map { build(it, tracker.episode, summary, rules.version, now) }
        return data.copy(pending = fresh + events.map(::encode))
    }

    fun build(t: ShieldEngine.Transition, ep: Episode, summary: EpisodeSignal, rulesVersion: String, now: Long): EpisodeEvent {
        val ends = t.trigger == "dismissed" || t.trigger == "closed"
        return EpisodeEvent(
            eventId = UUID.randomUUID().toString(),
            episodeId = t.episodeId ?: ep.id ?: UUID.randomUUID().toString(),
            userId = Ruko.userId, // the same id /v1/decide uses
            ts = RequestBuilder.istIso(t.ts),
            trigger = t.trigger,
            rulesVersion = rulesVersion,
            summary = if (t.trigger == "closed") summary.copy(state = EpisodeState.NONE.wire) else summary,
            accounts = if (ends) emptyList() else accounts(ep, now),
        )
    }

    /** The episode's own accounts: bait senders and payees, the most recent 10. */
    fun accounts(ep: Episode, now: Long): List<EpisodeAccount> {
        val out = ArrayList<EpisodeAccount>()
        ep.bait.filter { it.counterparty != null }.groupBy { it.counterparty!! }.forEach { (upi, list) ->
            out += EpisodeAccount(upi, "bait_sender", list.size, list.sumOf { it.amount }, minutesAgo(now, list.minOf { it.ts }))
        }
        val firstStep = HashMap<String, Int>()
        ep.outs.forEachIndexed { i, o -> o.counterparty?.let { firstStep.putIfAbsent(it, i + 1) } }
        ep.outs.filter { it.counterparty != null }.groupBy { it.counterparty!! }.forEach { (upi, list) ->
            out += EpisodeAccount(
                upi, "payee", list.size, list.sumOf { it.amount }, minutesAgo(now, list.minOf { it.ts }),
                via = if (list.last().fromSms) "other_app" else "this_app",
                step = firstStep[upi],
            )
        }
        return out.sortedByDescending { it.firstSeenMinAgo }.takeLast(MAX_ACCOUNTS)
    }

    private fun minutesAgo(now: Long, ts: Long) = maxOf(0.0, (now - ts) / 60_000.0)

    private fun encode(e: EpisodeEvent) = RukoJson.encodeToString(EpisodeEvent.serializer(), e)

    /** A queued event and its time, or null if it can't be read. */
    private fun decode(s: String): Pair<EpisodeEvent, Long>? = runCatching {
        val e = RukoJson.decodeFromString(EpisodeEvent.serializer(), s)
        e to OffsetDateTime.parse(e.ts).toInstant().toEpochMilli()
    }.getOrNull()

    /** Send whatever is queued as soon as there is a network. */
    fun schedule(context: Context) {
        if (EpisodeStore(context).load().pending.isEmpty()) return
        val request = OneTimeWorkRequestBuilder<EventSendWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(WORK, ExistingWorkPolicy.KEEP, request)
    }

    /** Send queued events in order; stop at the first failure so WorkManager retries later. */
    suspend fun flush(context: Context): Boolean = withContext(Dispatchers.IO) {
        val store = EpisodeStore(context)
        val accounts = AccountStore(context)
        val consents = accounts.loadConsents()
        if (!consents.shareAccounts || !consents.moneyWatch) {
            store.update { it.copy(pending = emptyList()) }
            return@withContext true
        }
        for (raw in store.load().pending) {
            val event = decode(raw)?.first
            if (event == null) {
                store.update { d -> d.copy(pending = d.pending - raw) }
                continue
            }
            val reply = try {
                ApiClient.events.episode(event)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                Log.w(TAG, "episode event not sent, will retry", e)
                return@withContext false
            }
            val data = store.update { d ->
                val live = d.watcher.episode.state.live
                d.copy(
                    pending = d.pending - raw,
                    serverRisk = if (live) reply.episodeRisk else null,
                    serverMessageKey = if (live) reply.messageKey else null,
                )
            }
            ShieldController.live.value = data
            // §8.4: "high" upgrades the Home card and sends a stronger warning. It still never blocks.
            if (reply.episodeRisk == "high" && data.watcher.episode.state.live) {
                ShieldNotifier.showConfirmed(context, accounts.loadProfile()?.language)
            }
        }
        true
    }
}

/** WorkManager job for [EventSender.flush]: needs a network, retries with exponential backoff. */
class EventSendWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result = if (EventSender.flush(applicationContext)) Result.success() else Result.retry()
}
