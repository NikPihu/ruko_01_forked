package com.ruko.demo.ui.alerts

import android.net.Uri
import kotlin.math.ceil

/** What the user did on an alert. [wire] is the feedback name the server will get (c2-0.8). */
enum class AlertAction(val wire: String) {
    TIP_SEEN("tip_seen"),
    PROCEEDED("proceeded"), // slid to pay on the T2 card
    CANCELLED("cancelled_from_alert"),
    CALLED_TRUSTED("called_trusted"),
    MESSAGED_TRUSTED("messaged_trusted"),
    CALLED_1930("called_1930"),
    WAITED("waited"),
    I_KNOW_THEM("i_know_them"),
    PAID_AFTER_PAUSE("paid_after_pause"),
}

/** Answers to "How do you know this person?" ([wire] is the feedback `why`). */
enum class KnowWhy(val wire: String) { FAMILY("family"), FRIEND("friend"), SHOP("shop"), LANDLORD("landlord"), EMPLOYER("employer"), OTHER("other") }

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
