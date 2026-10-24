package com.ruko.demo.shield

import android.app.Notification
import android.content.Context
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import androidx.core.app.NotificationManagerCompat
import com.ruko.demo.data.AccountStore
import com.ruko.demo.signals.MessageCheck
import com.ruko.demo.signals.Signals
import com.ruko.demo.ui.scamTagRes
import java.util.concurrent.Executors

/**
 * "Check chat messages" (Step 7): reads new notifications from chat apps (WhatsApp, Telegram...,
 * the list is in contracts/watch_rules.json), checks the text with the lure model on the phone and
 * forgets it. A scam script gets the "may be a scam" notification and, with "Early warnings" on,
 * a `lure_seen` tag for the server (source "notification"). The text is never stored or sent.
 * Android only calls this after the user grants notification access in Settings.
 */
class ChatListener : NotificationListenerService() {
    private val io = Executors.newSingleThreadExecutor()

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val app = applicationContext
        if (sbn.packageName == app.packageName || sbn.isOngoing) return
        val n = sbn.notification ?: return
        if (n.flags and Notification.FLAG_GROUP_SUMMARY != 0) return
        val extras = n.extras ?: return
        val text = (extras.getCharSequence(Notification.EXTRA_BIG_TEXT) ?: extras.getCharSequence(Notification.EXTRA_TEXT))?.toString()
        if (text.isNullOrBlank()) return
        val pkg = sbn.packageName
        io.execute {
            try {
                if (pkg !in WatchRules.load(app).chatApps) return@execute
                val store = AccountStore(app)
                if (!store.loadConsents().chatLure) return@execute
                Signals.init(app)
                // A chat comes from a person, so the "looks AI-written" hint applies.
                val m = MessageCheck.check(null, text, sbn.postTime, Signals.classifier, Signals.aiText, emptyList(), fromPerson = true)
                val tag = m.scamTag ?: return@execute
                if (m.otp) return@execute
                ShieldNotifier.showScamSms(
                    app, store.loadProfile()?.language, { c -> c.getString(scamTagRes(tag)) }, m.aiWritten == true,
                    Math.floorMod(pkg.hashCode(), 50),
                )
                WatchSender.report(app, Sighting.Lure(tag, m.scamConf ?: 0.0, "notification", m.aiWritten, m.handles))
            } catch (e: Exception) {
                Log.w("ChatListener", "chat message check failed", e)
            }
        }
    }

    companion object {
        /** True once the user has given Cache Pay notification access in Settings. */
        fun granted(context: Context): Boolean = context.packageName in NotificationManagerCompat.getEnabledListenerPackages(context)
    }
}
