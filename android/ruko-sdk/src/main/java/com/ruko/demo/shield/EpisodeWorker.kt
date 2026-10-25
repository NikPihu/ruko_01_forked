package com.ruko.demo.shield

import android.content.Context
import android.content.pm.ServiceInfo
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.work.CoroutineWorker
import androidx.work.ForegroundInfo
import androidx.work.WorkerParameters
import com.ruko.sdk.R
import com.ruko.sdk.Ruko
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** Applies transactions from the SMS receiver to the episode, saves it and notifies. */
class EpisodeWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val raw = inputData.getString(TXNS) ?: return@withContext Result.success()
        val txns = runCatching { ShieldController.json.decodeFromString(ShieldController.txnList, raw) }.getOrNull()
            ?: return@withContext Result.failure()
        ShieldController.process(applicationContext, txns)
        Result.success()
    }

    // Only used for expedited work before Android 12.
    override suspend fun getForegroundInfo(): ForegroundInfo {
        ShieldNotifier.ensureChannel(applicationContext)
        val n = NotificationCompat.Builder(applicationContext, ShieldNotifier.CHANNEL)
            .setSmallIcon(Ruko.config.smallIcon)
            .setContentTitle(applicationContext.getString(R.string.shield_working))
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .build()
        return if (Build.VERSION.SDK_INT >= 29) ForegroundInfo(300, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC) else ForegroundInfo(300, n)
    }

    companion object {
        const val TXNS = "txns"
    }
}
