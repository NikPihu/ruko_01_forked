package com.ruko.demo.shield

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony
import android.util.Log
import com.ruko.demo.BuildConfig
import com.ruko.demo.data.AccountStore
import com.ruko.demo.signals.BankSms
import com.ruko.demo.signals.MessageCheck
import com.ruko.demo.signals.MessageScan
import com.ruko.demo.signals.MoneyTxn
import com.ruko.demo.signals.Signals
import com.ruko.demo.ui.scamTagRes

/**
 * SMS_RECEIVED wakes the app even when it is not running (the broadcast is on Android's exempt
 * list). Bank alerts are parsed here and handed to EpisodeWorker; the text is never stored.
 * Also: a one-time code (OTP) that arrives during a call gets a full warning, with "SMS scam
 * check" and "Call checks" on (A5). Ships disabled; ShieldController enables it when "Watch my
 * money alerts" or "SMS scam check" is switched on.
 */
class SmsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return
        val messages = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return
        // A long alert arrives in parts; join them per sender.
        val bySender = messages.groupBy { it.originatingAddress }
        // If the consents cannot be read, bank alerts go on as before and no OTP warning is shown.
        val consents = runCatching { AccountStore(context).loadConsents() }.getOrNull()
        if (consents != null && consents.smsLure) warnScamMessages(context, bySender.mapValues { (_, parts) -> parts.joinToString("") { it.messageBody.orEmpty() } })
        if (consents != null && consents.smsLure && consents.callSignals) {
            val now = System.currentTimeMillis()
            val otpOnCall = bySender.values.any { parts -> MessageCheck.isOtp(parts.joinToString("") { it.messageBody.orEmpty() }) } &&
                MessageScan.callNow(context, now) != null
            if (otpOnCall) ShieldNotifier.showOtpOnCall(context, runCatching { AccountStore(context).loadProfile()?.language }.getOrNull())
        }
        if (consents != null && !consents.moneyWatch) return
        val txns = bySender.mapNotNull { (sender, parts) ->
            // Debug builds accept numbered senders, so the emulator's `sms send` can play a bank.
            if (!BankSms.trustedSender(sender, allowNumbers = BuildConfig.DEBUG)) return@mapNotNull null
            val body = parts.joinToString("") { it.messageBody.orEmpty() }
            BankSms.parse(body, parts.first().timestampMillis + ShieldController.debugOffsetMs)
        }
        ShieldController.enqueue(context, txns)
    }

    /**
     * A new SMS that matches a scam script gets a "may be a scam" notification (A5). Bank alerts
     * and OTPs are skipped (OTPs have their own warning). The models load off the main thread.
     */
    private fun warnScamMessages(context: Context, bodies: Map<String?, String>) {
        val pending = goAsync()
        Thread {
            try {
                Signals.init(context.applicationContext)
                val language = runCatching { AccountStore(context).loadProfile()?.language }.getOrNull()
                for ((sender, body) in bodies) {
                    if (BankSms.trustedSender(sender, allowNumbers = BuildConfig.DEBUG) && BankSms.parse(body, 0L) != null) continue
                    val m = MessageCheck.check(sender, body, System.currentTimeMillis(), Signals.classifier, Signals.aiText, emptyList())
                    val tag = m.scamTag ?: continue
                    if (m.otp) continue
                    ShieldNotifier.showScamSms(
                        context, language, { c -> c.getString(scamTagRes(tag)) }, m.aiWritten == true,
                        Math.floorMod(sender.orEmpty().hashCode(), 50),
                    )
                }
            } catch (e: Exception) {
                Log.w("SmsReceiver", "scam message check failed", e)
            } finally {
                pending.finish()
            }
        }.start()
    }

    companion object {
        /** For tests and the debug panel: the same path without a real SMS. */
        fun parsed(sender: String, body: String, ts: Long): MoneyTxn? =
            if (BankSms.trustedSender(sender, allowNumbers = BuildConfig.DEBUG)) BankSms.parse(body, ts) else null
    }
}
