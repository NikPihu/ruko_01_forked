package com.ruko.demo.shield

import android.Manifest.permission.READ_SMS
import android.content.Context
import android.content.pm.PackageManager
import android.provider.Telephony
import androidx.core.content.ContextCompat
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.ruko.demo.BuildConfig
import com.ruko.demo.data.AccountStore
import com.ruko.demo.signals.BankSms
import com.ruko.demo.signals.MoneyTxn
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Every 6 hours (and once as the 30-day backfill when the switch goes on): re-reads the SMS inbox
 * since the last scan, to cover missed broadcasts, reboots and force-stops, and closes quiet episodes.
 */
class CatchUpWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val ctx = applicationContext
        val now = ShieldController.now()
        val backfill = inputData.getBoolean(BACKFILL, false)
        val since = if (backfill) {
            now - ShieldController.BACKFILL_DAYS * 86_400_000L
        } else {
            EpisodeStore(ctx).load().lastScanTs.takeIf { it > 0 } ?: (now - 86_400_000L)
        }
        // The backfill also replays this app's own recent payments.
        val appPayments = if (backfill) AccountStore(ctx).loadPayments().filter { it.ts >= since } else emptyList()
        ShieldController.process(ctx, appPayments + scan(ctx, since), markScanned = now)
        EventSender.schedule(ctx) // flush anything still queued
        Result.success()
    }

    private fun scan(context: Context, since: Long): List<MoneyTxn> {
        if (ContextCompat.checkSelfPermission(context, READ_SMS) != PackageManager.PERMISSION_GRANTED) return emptyList()
        val out = ArrayList<MoneyTxn>()
        try {
            context.contentResolver.query(
                Telephony.Sms.Inbox.CONTENT_URI,
                arrayOf(Telephony.Sms.BODY, Telephony.Sms.DATE, Telephony.Sms.ADDRESS),
                "${Telephony.Sms.DATE} > ?",
                arrayOf(since.toString()),
                "${Telephony.Sms.DATE} ASC",
            )?.use { c ->
                while (c.moveToNext() && out.size < MAX_MESSAGES) {
                    if (!BankSms.trustedSender(c.getString(2), allowNumbers = BuildConfig.DEBUG)) continue
                    BankSms.parse(c.getString(0) ?: continue, c.getLong(1))?.let(out::add)
                }
            }
        } catch (e: SecurityException) {
            return emptyList()
        }
        return out
    }

    companion object {
        const val BACKFILL = "backfill"
        private const val MAX_MESSAGES = 2_000
    }
}
