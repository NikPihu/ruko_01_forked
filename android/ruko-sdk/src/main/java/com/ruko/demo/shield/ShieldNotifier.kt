package com.ruko.demo.shield

import android.Manifest.permission.POST_NOTIFICATIONS
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.ruko.sdk.Ruko
import com.ruko.sdk.R
import com.ruko.demo.data.AlertEntry
import com.ruko.demo.data.AlertKind
import com.ruko.demo.ui.scamTagRes
import java.util.Locale

/**
 * Gentle warnings from the watcher. It only warns; it never blocks a payment. Every warning is also
 * kept for the Alerts screen ([AlertRecorder]), even when notifications are off.
 */
object ShieldNotifier {
    const val CHANNEL = "scam_shield_alerts"
    private const val CONFIRMED_ID = 200
    private const val OTP_ON_CALL_ID = 300
    private const val SCAM_SMS_ID = 400 // + 0..49 per sender

    fun ensureChannel(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(CHANNEL) != null) return
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL, context.getString(R.string.shield_channel_name), NotificationManager.IMPORTANCE_DEFAULT).apply {
                description = context.getString(R.string.shield_channel_desc)
            },
        )
    }

    fun show(context: Context, alert: ShieldEngine.Alert, language: String?) {
        val kind = when (alert.kind) {
            ShieldEngine.AlertKind.ACTIVE -> AlertKind.TASK_SCAM
            ShieldEngine.AlertKind.OUT_OTHER_APP -> AlertKind.PAID_OTHER_APP
        }
        AlertRecorder.record(context, AlertEntry(System.currentTimeMillis(), kind))
        val (title, body) = text(localized(context, language), alert)
        post(context, alert.kind.ordinal + 100, title, body)
    }

    /** A stronger notification when the server confirms the accounts look like a ring (§8.4). */
    fun showConfirmed(context: Context, language: String?) {
        AlertRecorder.record(context, AlertEntry(System.currentTimeMillis(), AlertKind.RING_CONFIRMED))
        val c = localized(context, language)
        post(context, CONFIRMED_ID, c.getString(R.string.shield_confirmed_title), c.getString(R.string.shield_confirmed_text))
    }

    /** An OTP arrived while a call is going on: whoever asks for it on the call is a scammer (A5). */
    fun showOtpOnCall(context: Context, language: String?) {
        AlertRecorder.record(context, AlertEntry(System.currentTimeMillis(), AlertKind.OTP_ON_CALL))
        val c = localized(context, language)
        post(context, OTP_ON_CALL_ID, c.getString(R.string.msg_otp_call_title), c.getString(R.string.msg_otp_call_text))
    }

    /**
     * A new SMS matches a scam script (A5). Says which kind and, when known, that it looks
     * AI-written; never quotes the message. Tapping opens Message check. [source] is "sms" or "chat".
     */
    fun showScamSms(context: Context, language: String?, tag: String, aiWritten: Boolean, id: Int, source: String) {
        AlertRecorder.record(context, AlertEntry(System.currentTimeMillis(), AlertKind.SCAM_MESSAGE, tag, source, aiWritten))
        val c = localized(context, language)
        val body = c.getString(R.string.msg_scam_notify_text, c.getString(scamTagRes(tag))) +
            if (aiWritten) " " + c.getString(R.string.msg_scam_notify_ai) else ""
        post(context, SCAM_SMS_ID + id, c.getString(R.string.msg_scam_notify_title), body, Ruko.OPEN_MESSAGES)
    }

    fun post(context: Context, id: Int, title: String, body: String, open: String? = null) {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(context, POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            return // notifications off: the Home card still shows the episode
        }
        ensureChannel(context)
        // The host app decides what a tap opens (its own activity, its "Message check" screen).
        val intent = Ruko.config.openApp(context, open)
        val tap = PendingIntent.getActivity(
            context, id,
            intent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val n = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(Ruko.config.smallIcon)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(tap)
            .setAutoCancel(true)
            .build()
        try {
            NotificationManagerCompat.from(context).notify(id, n)
        } catch (e: SecurityException) {
            // permission revoked between the check and the call
        }
    }

    fun text(c: Context, a: ShieldEngine.Alert): Pair<String, String> {
        val s = a.summary
        return when (a.kind) {
            ShieldEngine.AlertKind.ACTIVE -> c.getString(R.string.shield_active_title) to
                c.getString(R.string.shield_active_text, rupees(s.baitInr), s.baitCredits, rupees(s.outsInr), s.newPayees)
            ShieldEngine.AlertKind.OUT_OTHER_APP -> c.getString(R.string.shield_out_title) to
                c.getString(R.string.shield_out_text, rupees(a.amountInr))
        }
    }

    /** Alerts follow the language chosen in the profile, not the phone's. */
    fun localized(context: Context, language: String?): Context {
        if (language.isNullOrBlank()) return context
        val config = Configuration(context.resources.configuration).apply { setLocale(Locale.forLanguageTag(language)) }
        return context.createConfigurationContext(config)
    }

    fun rupees(x: Double): String = "₹" + String.format(Locale("en", "IN"), "%,.0f", x)
}
