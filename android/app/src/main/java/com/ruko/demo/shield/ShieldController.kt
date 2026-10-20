package com.ruko.demo.shield

import android.Manifest.permission.READ_SMS
import android.Manifest.permission.RECEIVE_SMS
import android.content.ComponentName
import android.content.Context
import android.content.pm.PackageManager
import android.util.Log
import androidx.compose.runtime.mutableStateOf
import androidx.core.content.ContextCompat
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.OutOfQuotaPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.workDataOf
import com.ruko.demo.data.AccountStore
import com.ruko.demo.data.Consents
import com.ruko.demo.net.EpisodeSignal
import com.ruko.demo.signals.Flow
import com.ruko.demo.signals.MoneyTxn
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * The background task-scam watcher: on/off, receiver and work scheduling, backfill, and the one
 * place every transaction goes through (SMS receiver, catch-up scan, payments in this app).
 * No foreground service: an SMS broadcast wakes the app, WorkManager does the rest.
 */
object ShieldController {
    private const val TAG = "Shield"
    const val CATCH_UP_WORK = "shield_catch_up"
    const val BACKFILL_WORK = "shield_backfill"
    const val BACKFILL_DAYS = 30

    internal val json = Json { ignoreUnknownKeys = true }
    internal val txnList = ListSerializer(MoneyTxn.serializer())

    /** Debug panel "+1 day": shifts the watcher's clock (in memory only). */
    @Volatile
    var debugOffsetMs = 0L

    fun now(): Long = System.currentTimeMillis() + debugOffsetMs

    /** The latest watcher data for the UI (Home card, debug panel). Null while the watcher is off. */
    val live = mutableStateOf<ShieldData?>(null)

    private val io = Executors.newSingleThreadExecutor()

    fun refresh(context: Context, consents: Consents) {
        live.value = if (isOn(consents)) EpisodeStore(context).load() else null
    }

    fun dismissAsync(context: Context) = io.execute { dismiss(context) }

    // ---------- debug panel ----------

    /** A fake ₹150 "reward" from a new stranger, through the same path as a real bank SMS. */
    fun simulateBait(context: Context) = io.execute {
        val n = (live.value?.watcher?.episode?.bait?.size ?: 0) + 1
        process(context, listOf(MoneyTxn(now(), 150.0, Flow.IN, "task.reward$n@ybl", fromSms = true)))
    }

    /** A fake payment from another app (a debit SMS), each one bigger than the last. */
    fun simulateDebit(context: Context) = io.execute {
        val outs = live.value?.watcher?.episode?.outs.orEmpty()
        val amount = outs.lastOrNull()?.let { Math.round(it.amount * 2.4 / 100.0) * 100.0 } ?: 1_000.0
        process(context, listOf(MoneyTxn(now(), amount, Flow.OUT, "unlock.level${outs.size + 1}@ybl", fromSms = true)))
    }

    /** "+1 day": moves the watcher's clock forward, to test the 30-day close. */
    fun addDay(context: Context) = io.execute {
        debugOffsetMs += 86_400_000L
        process(context, emptyList())
    }

    fun isOn(consents: Consents): Boolean = consents.moneyWatch

    /** Bait can only be seen when SMS can be read; otherwise the bait fields are unknown. */
    fun smsRead(context: Context, consents: Consents): Boolean = consents.moneyWatch && (
        granted(context, RECEIVE_SMS) || granted(context, READ_SMS)
        )

    /** Called after the switch is on and the permissions are answered. */
    fun enable(context: Context) {
        setReceiver(context, true)
        ShieldNotifier.ensureChannel(context)
        val wm = WorkManager.getInstance(context)
        wm.enqueueUniquePeriodicWork(
            CATCH_UP_WORK, ExistingPeriodicWorkPolicy.KEEP,
            PeriodicWorkRequestBuilder<CatchUpWorker>(6, TimeUnit.HOURS).build(),
        )
        wm.enqueueUniqueWork(
            BACKFILL_WORK, ExistingWorkPolicy.KEEP,
            OneTimeWorkRequestBuilder<CatchUpWorker>().setInputData(workDataOf(CatchUpWorker.BACKFILL to true)).build(),
        )
    }

    /** On every app start while the switch is on: receiver and the 6-hourly scan, no backfill. */
    fun ensureRunning(context: Context, consents: Consents) {
        if (!isOn(consents)) return
        setReceiver(context, true)
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            CATCH_UP_WORK, ExistingPeriodicWorkPolicy.KEEP,
            PeriodicWorkRequestBuilder<CatchUpWorker>(6, TimeUnit.HOURS).build(),
        )
    }

    /** Switching off stops everything and deletes the money history and episode. */
    fun disable(context: Context) {
        live.value = null
        setReceiver(context, false)
        WorkManager.getInstance(context).apply {
            cancelUniqueWork(CATCH_UP_WORK)
            cancelUniqueWork(BACKFILL_WORK)
            cancelUniqueWork(EventSender.WORK)
        }
        EpisodeStore(context).delete()
    }

    /** "Delete money history": keeps watching, forgets everything seen so far. */
    fun deleteHistory(context: Context) {
        live.value = EpisodeStore(context).update { ShieldData(lastScanTs = now()) }
    }

    /** Hand transactions to the worker (from the SMS receiver). */
    fun enqueue(context: Context, txns: List<MoneyTxn>) {
        if (txns.isEmpty()) return
        val request = OneTimeWorkRequestBuilder<EpisodeWorker>()
            .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
            .setInputData(workDataOf(EpisodeWorker.TXNS to json.encodeToString(txnList, txns)))
            .build()
        WorkManager.getInstance(context).enqueue(request)
    }

    /** A payment finished in this app. */
    fun recordAppPayment(context: Context, upiId: String, amountInr: Double?) {
        if (amountInr == null || upiId.isBlank()) return
        process(context, listOf(MoneyTxn(now(), amountInr, Flow.OUT, upiId.trim().lowercase())))
    }

    /** Apply transactions, save, notify, and queue episode events. Safe from any thread. */
    fun process(context: Context, txns: List<MoneyTxn>, markScanned: Long? = null) {
        val accounts = AccountStore(context)
        val consents = accounts.loadConsents()
        if (!isOn(consents)) return
        val rules = EpisodeStore.rules(context)
        val sms = smsRead(context, consents)
        var result: ShieldEngine.Result? = null
        EpisodeStore(context).update { data ->
            val r = ShieldEngine.apply(rules, sms, data, txns, now())
            result = r
            val withEvents = EventSender.queue(r.data, r.transitions, consents, accounts.loadProfile()?.localId, rules.version, now())
            if (markScanned != null) withEvents.copy(lastScanTs = markScanned) else withEvents
        }
        val r = result ?: return
        live.value = r.data
        val language = accounts.loadProfile()?.language
        r.alerts.forEach { ShieldNotifier.show(context, it, language) }
        if (r.transitions.isNotEmpty()) EventSender.schedule(context)
        Log.i(TAG, "processed ${txns.size} txns, state ${r.data.watcher.episode.state}")
    }

    /** "I know them / it's a real job" on the Home card. */
    fun dismiss(context: Context) {
        val accounts = AccountStore(context)
        val consents = accounts.loadConsents()
        val rules = EpisodeStore.rules(context)
        var transitions: List<ShieldEngine.Transition> = emptyList()
        live.value = EpisodeStore(context).update { data ->
            val r = ShieldEngine.dismiss(rules, smsRead(context, consents), data, now())
            transitions = r.transitions
            EventSender.queue(r.data, r.transitions, consents, accounts.loadProfile()?.localId, rules.version, now())
        }
        if (transitions.isNotEmpty()) EventSender.schedule(context)
    }

    /** `context.episode` for the payment being checked; null when the watcher is off. */
    fun summary(context: Context, consents: Consents, payee: String?): EpisodeSignal? {
        if (!isOn(consents)) return null
        val data = EpisodeStore(context).load()
        return EpisodeTracker(EpisodeStore.rules(context), smsRead(context, consents), data.watcher).summary(now(), payee)
    }

    private fun setReceiver(context: Context, on: Boolean) {
        context.packageManager.setComponentEnabledSetting(
            ComponentName(context, SmsReceiver::class.java),
            if (on) PackageManager.COMPONENT_ENABLED_STATE_ENABLED else PackageManager.COMPONENT_ENABLED_STATE_DISABLED,
            PackageManager.DONT_KILL_APP,
        )
    }

    private fun granted(context: Context, p: String) = ContextCompat.checkSelfPermission(context, p) == PackageManager.PERMISSION_GRANTED
}
