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
import com.ruko.demo.MainActivity
import com.ruko.demo.R
import java.util.Locale

/** Gentle warnings from the watcher. It only warns; it never blocks a payment. */
object ShieldNotifier {
    const val CHANNEL = "scam_shield_alerts"
    private const val CONFIRMED_ID = 200

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
        val (title, body) = text(localized(context, language), alert)
        post(context, alert.kind.ordinal + 100, title, body)
    }

    /** A stronger notification when the server confirms the accounts look like a ring (§8.4). */
    fun showConfirmed(context: Context, language: String?) {
        val c = localized(context, language)
        post(context, CONFIRMED_ID, c.getString(R.string.shield_confirmed_title), c.getString(R.string.shield_confirmed_text))
    }

    fun post(context: Context, id: Int, title: String, body: String) {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(context, POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            return // notifications off: the Home card still shows the episode
        }
        ensureChannel(context)
        val open = PendingIntent.getActivity(
            context, 0,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val n = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(open)
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
