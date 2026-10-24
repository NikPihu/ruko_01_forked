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
import com.ruko.demo.net.MoneyReceived
import com.ruko.demo.net.RequestBuilder
import com.ruko.demo.net.RukoJson
import com.ruko.demo.signals.Flow
import com.ruko.demo.signals.MoneyTxn
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import java.io.File
import java.util.UUID
import java.util.concurrent.TimeUnit

/** The rules for reporting money received, kept free of Android so they can be tested. */
object ReceivedPolicy {
    /** Needs the money watch (it reads the bank SMS) and its own switch, both off by default (rule 7). */
    fun allowed(c: Consents): Boolean = c.moneyWatch && c.shareReceived

    /**
     * One event per credit the watcher took as new: money in, read from a bank SMS. Never this app's
     * own payments (they are payments, POST /v1/payment/outcome) and never the SMS text (rule 2).
     */
    fun events(txns: List<MoneyTxn>, userId: String, newId: () -> String = { UUID.randomUUID().toString() }): List<MoneyReceived> =
        txns.filter { it.flow == Flow.IN && it.fromSms }
            .map { MoneyReceived(newId(), userId, it.counterparty, it.amount, RequestBuilder.istIso(it.ts), senderName = it.counterpartyName) }
}

/** Encrypted queue of credits waiting to be sent. */
@Serializable
data class ReceivedQueue(val pending: List<String> = emptyList())

/**
 * Money received to the server (POST /v1/payment/received, c2-0.11), only with "Share money
 * received" on. Events wait encrypted and go out through WorkManager when there is a network, like
 * early warnings; the server records an event_id once, so retries are safe. Unsent events expire
 * after a week; switching the sharing off deletes them.
 */
object ReceivedSender {
    const val WORK = "received_events"
    private const val FILE = "received.json"
    private const val TAG = "ReceivedSender"
    private const val MAX_AGE_MS = 7 * 86_400_000L
    private val LOCK = Any()

    fun report(context: Context, txns: List<MoneyTxn>) {
        try {
            if (!ReceivedPolicy.allowed(AccountStore(context).loadConsents())) return
            val events = ReceivedPolicy.events(txns, DemoConfig.USER_ID)
            if (events.isEmpty()) return
            update(context) { q -> q.copy(pending = q.pending + events.map { RukoJson.encodeToString(MoneyReceived.serializer(), it) }) }
            schedule(context)
        } catch (e: Exception) {
            Log.w(TAG, "money received not queued", e)
        }
    }

    fun clear(context: Context) {
        synchronized(LOCK) { store(context).delete(FILE) }
        WorkManager.getInstance(context).cancelUniqueWork(WORK)
    }

    private fun schedule(context: Context) {
        val request = OneTimeWorkRequestBuilder<ReceivedSendWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(WORK, ExistingWorkPolicy.APPEND_OR_REPLACE, request)
    }

    /** Send in order; stop at the first failure so WorkManager retries later. */
    suspend fun flush(context: Context): Boolean = withContext(Dispatchers.IO) {
        if (!ReceivedPolicy.allowed(AccountStore(context).loadConsents())) {
            clear(context)
            return@withContext true
        }
        for (raw in update(context) { it }.pending) {
            val event = runCatching { RukoJson.decodeFromString(MoneyReceived.serializer(), raw) }.getOrNull()
            val tooOld = event == null ||
                System.currentTimeMillis() - java.time.OffsetDateTime.parse(event.ts).toInstant().toEpochMilli() > MAX_AGE_MS
            if (!tooOld) {
                try {
                    ApiClient.events.moneyReceived(event!!)
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    Log.w(TAG, "money received not sent, will retry", e)
                    return@withContext false
                }
            }
            update(context) { it.copy(pending = it.pending - raw) }
        }
        true
    }

    private fun update(context: Context, change: (ReceivedQueue) -> ReceivedQueue): ReceivedQueue = synchronized(LOCK) {
        val s = store(context)
        val current = runCatching { s.read(FILE)?.let { RukoJson.decodeFromString(ReceivedQueue.serializer(), it.decodeToString()) } }.getOrNull() ?: ReceivedQueue()
        val next = change(current)
        if (next != current) s.write(FILE, RukoJson.encodeToString(ReceivedQueue.serializer(), next).encodeToByteArray())
        next
    }

    private fun store(context: Context) = SecureStore(File(context.noBackupFilesDir, "secure"))
}

/** WorkManager job for [ReceivedSender.flush]: needs a network, retries with exponential backoff. */
class ReceivedSendWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result = if (ReceivedSender.flush(applicationContext)) Result.success() else Result.retry()
}
