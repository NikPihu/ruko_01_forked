package com.ruko.demo.ui.alerts

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.ruko.demo.R
import com.ruko.demo.shield.ShieldNotifier
import java.util.concurrent.TimeUnit

/**
 * "Wait 30 min, then decide": a local notification when the pause ends. Nothing about the
 * payment is in it (no amount, no payee), and it never pays or cancels anything by itself.
 */
object PauseReminder {
    private const val WORK = "ruko_pause_reminder"
    private const val NOTIFICATION_ID = 300

    fun schedule(context: Context, pauseEndsAtMs: Long, language: String?) {
        val delay = (pauseEndsAtMs - System.currentTimeMillis()).coerceAtLeast(0)
        val request = OneTimeWorkRequestBuilder<PauseReminderWorker>()
            .setInitialDelay(delay, TimeUnit.MILLISECONDS)
            .setInputData(workDataOf(PauseReminderWorker.LANGUAGE to language))
            .build()
        // One paused payment at a time: a newer pause replaces the older reminder.
        WorkManager.getInstance(context).enqueueUniqueWork(WORK, ExistingWorkPolicy.REPLACE, request)
    }

    fun show(context: Context, language: String?) {
        val c = ShieldNotifier.localized(context, language)
        ShieldNotifier.post(context, NOTIFICATION_ID, c.getString(R.string.alert_reminder_title), c.getString(R.string.alert_reminder_body))
    }
}

class PauseReminderWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        PauseReminder.show(applicationContext, inputData.getString(LANGUAGE))
        return Result.success()
    }

    companion object {
        const val LANGUAGE = "language"
    }
}
