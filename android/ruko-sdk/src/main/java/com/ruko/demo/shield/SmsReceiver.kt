package com.ruko.demo.shield

import com.ruko.sdk.Ruko
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony
import android.util.Log
import com.ruko.demo.data.AccountStore
import com.ruko.demo.signals.BankSms
import com.ruko.demo.signals.MessageCheck
import com.ruko.demo.signals.MessageScan
import com.ruko.demo.signals.MoneyTxn
import com.ruko.demo.signals.OtpPurpose
import com.ruko.demo.signals.Signals
import com.ruko.demo.signals.callerHash

/**
 * SMS_RECEIVED wakes the app even when it is not running (the broadcast is on Android's exempt
 * list). Every message is scam-checked first; a bank alert that does not read like a scam is parsed
 * and handed to EpisodeWorker; the text is never stored.
 * Also: a one-time code (OTP) for UPI or a bank that arrives during a call gets a full warning, with "SMS scam
 * check" and "Call signals" on (A5). Ships disabled; ShieldController enables it when "Watch my
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
        var otpOnCall: OtpPurpose? = null
        if (consents != null && consents.smsLure && consents.callSignals) {
            // Only an OTP for UPI or a bank is a takeover warning; one for an order or a social app is not.
            val purpose = bySender.entries.mapNotNull { (sender, parts) ->
                MessageCheck.otpPurpose(sender, parts.joinToString("") { it.messageBody.orEmpty() })?.takeIf { it.forMoney }
            }.minOrNull() // UPI before BANK
            if (purpose != null && MessageScan.callNow(context, System.currentTimeMillis()) != null) {
                otpOnCall = purpose
                ShieldNotifier.showOtpOnCall(context, runCatching { AccountStore(context).loadProfile()?.language }.getOrNull())
            }
        }
        val warn = consents != null && consents.smsLure
        val count = consents == null || consents.moneyWatch
        if (!warn && !count) return
        triageMessages(context, bySender.mapValues { (_, parts) ->
            parts.joinToString("") { it.messageBody.orEmpty() } to parts.first().timestampMillis + ShieldController.debugOffsetMs
        }, warn, count, otpOnCall)
    }

    /**
     * Off the main thread (the models load here): each message is checked once by [SmsTriage]. A
     * scam script gets a "may be a scam" notification when [warn] (A5), and is never counted as a
     * bank alert; the rest go to EpisodeWorker when [count].
     */
    private fun triageMessages(
        context: Context, messages: Map<String?, Pair<String, Long>>, warn: Boolean, count: Boolean, otpOnCall: OtpPurpose?,
    ) {
        val pending = goAsync()
        Thread {
            try {
                Signals.init(context.applicationContext)
                // The OTP-on-call early warning (c2-0.15): an account takeover in progress. Only the
                // call type and the caller's pseudonym, never the code, the sender or the text (rule 2).
                if (otpOnCall != null) {
                    val call = runCatching { Signals.sensor.readCall() }.getOrNull()
                    WatchSender.report(context, Sighting.OtpOnCall(call?.kind, call?.callerInContacts,
                        callerHash(call?.callerInContacts, call?.callerNumber), otpOnCall))
                }
                val language = if (warn) runCatching { AccountStore(context).loadProfile()?.language }.getOrNull() else null
                val txns = ArrayList<MoneyTxn>()
                for ((sender, message) in messages) {
                    val (body, ts) = message
                    // Debug builds accept numbered senders, so the emulator's `sms send` can play a bank.
                    val verdict = SmsTriage.triage(sender, body, ts, Signals.classifier, Signals.aiText, trustNumbers = Ruko.config.debugSenders)
                    if (count) verdict.txn?.let(txns::add)
                    val m = verdict.scam ?: continue
                    if (!warn) continue
                    val tag = m.scamTag ?: continue
                    WatchSender.report(context, Sighting.Lure(tag, m.scamConf ?: 0.0, "sms", m.aiWritten, m.handles))
                    ShieldNotifier.showScamSms(
                        context, language, tag, m.aiWritten == true, Math.floorMod(sender.orEmpty().hashCode(), 50), "sms",
                    )
                }
                ShieldController.enqueue(context, txns)
            } catch (e: Exception) {
                Log.w("SmsReceiver", "SMS check failed", e)
            } finally {
                pending.finish()
            }
        }.start()
    }

    companion object {
        /** For tests and the debug panel: the same path without a real SMS. */
        fun parsed(sender: String, body: String, ts: Long): MoneyTxn? =
            if (BankSms.trustedSender(sender, allowNumbers = Ruko.config.debugSenders)) BankSms.parse(body, ts) else null
    }
}
