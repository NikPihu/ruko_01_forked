package com.ruko.demo.ui.alerts

import android.net.Uri
import com.ruko.demo.net.FeedbackAction
import kotlin.math.ceil

/** What the user did on an alert, and the feedback action the server gets for it (c2-0.9). */
enum class AlertAction(val feedback: FeedbackAction) {
    TIP_SEEN(FeedbackAction.TIP_SEEN),
    PROCEEDED(FeedbackAction.SLID_TO_PAY), // slid to pay on the T2 card
    CANCELLED(FeedbackAction.CANCELLED_FROM_ALERT),
    CALLED_TRUSTED(FeedbackAction.CALLED_TRUSTED),
    MESSAGED_TRUSTED(FeedbackAction.MESSAGED_TRUSTED),
    CALLED_1930(FeedbackAction.CALLED_1930),
    WAITED(FeedbackAction.WAITED),
    I_KNOW_THEM(FeedbackAction.I_KNOW_THEM),
    PAID_AFTER_PAUSE(FeedbackAction.PAY_AFTER_PAUSE),
}

/** Timing rules of the alert screens, kept out of Compose so they can be tested. */
object AlertRules {
    /** The T2 card can only be slid after it has been on screen this long. */
    const val READ_GATE_MS = 5_000L

    /** The slide must reach this share of the track. */
    const val SLIDE_DONE = 0.85f

    fun slideEnabled(shownMs: Long, nowMs: Long): Boolean = nowMs - shownMs >= READ_GATE_MS

    fun readGateLeftSeconds(shownMs: Long, nowMs: Long): Int =
        ceil((READ_GATE_MS - (nowMs - shownMs)).coerceAtLeast(0) / 1000.0).toInt()

    /** The pause runs from the decision for `pause_minutes` (until c2-0.8 sends `pause_until`). */
    fun pauseEndsAt(decidedAtMs: Long, pauseMinutes: Int): Long = decidedAtMs + pauseMinutes.coerceAtLeast(0) * 60_000L

    /** "Pay anyway" stays hidden until the pause is over; then the user may still pay (warn, never block). */
    fun payAnywayVisible(nowMs: Long, pauseEndsAtMs: Long): Boolean = nowMs >= pauseEndsAtMs

    /** Whole minutes left, rounded up: "1 min" until the very end. */
    fun minutesLeft(nowMs: Long, pauseEndsAtMs: Long): Int =
        ceil((pauseEndsAtMs - nowMs).coerceAtLeast(0) / 60_000.0).toInt()
}

/**
 * The SMS to the trusted person. It carries the user's first name and nothing about the payment:
 * no amount, no payee (deck slide 6). [template] is `R.string.trusted_contact_sms`.
 */
object TrustedMessage {
    fun body(template: String, firstName: String): String = String.format(template, firstName.trim()).trim()

    fun smsUri(mobile: String): Uri = Uri.parse("smsto:${mobile.filter { it.isDigit() || it == '+' }}")
}

/** The screen after Pay. T1 adds none: its tip sits on the PIN screen. */
enum class AlertScreen { PIN, EXPLAIN, PAUSE, REVIEW, UNAVAILABLE }

/** [tier] null means Scam Shield could not answer (fail open). A tier this app does not know gets the T2 card. */
fun screenFor(tier: String?): AlertScreen = when (tier) {
    null -> AlertScreen.UNAVAILABLE
    "T0", "T1" -> AlertScreen.PIN
    "T3" -> AlertScreen.PAUSE
    "T4" -> AlertScreen.REVIEW
    else -> AlertScreen.EXPLAIN
}
