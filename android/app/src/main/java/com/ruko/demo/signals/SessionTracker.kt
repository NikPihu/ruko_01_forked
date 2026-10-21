package com.ruko.demo.signals

import com.ruko.demo.net.SessionSignal
import kotlin.math.round

/**
 * How the user behaves on the Pay screen of one payment (contract c2-0.5 `context.session`).
 *
 * A person being talked through a payment types the amount digit by digit as it is read out,
 * leaves the app for the call or WhatsApp and comes back to paste the UPI ID, and starts over.
 * This class only keeps times and counts in memory, for the payment being made: never the keys
 * typed and never which other app was opened. Field meanings: contracts/README.md.
 *
 * Plain Kotlin with the time passed in, so SessionTrackerTest can drive it without a phone.
 */
class SessionTracker {
    private var startedAt = 0L
    private var active = false
    private var paid = false
    private var touched = false // the user typed or picked something; an empty visit is not a try
    private val digitTimes = mutableListOf<Long>()
    private var edits = 0
    private var pasted = false
    private var pastedSecondsAfterReturn: Double? = null
    private var switches = 0
    private var awayMs = 0L
    private var backgroundAt = 0L
    private var returnedAt = 0L
    private val abandonedAt = ArrayDeque<Long>()

    /** Opening the Pay screen. A previous flow that was left without paying counts as abandoned. */
    fun start(now: Long) {
        if (active && !paid && touched) abandonedAt.addLast(now)
        startedAt = now
        active = true
        paid = false
        touched = false
        digitTimes.clear()
        edits = 0
        pasted = false
        pastedSecondsAfterReturn = null
        switches = 0
        awayMs = 0
        backgroundAt = 0
        returnedAt = 0
    }

    fun onAmountChange(old: String, new: String, now: Long) {
        if (!active) return
        touched = true
        val added = new.count(Char::isDigit) - old.count(Char::isDigit)
        if (added < 0 || new.length < old.length) edits++
        // One key press adds one digit; a paste of a whole amount is not typing rhythm.
        if (added == 1) digitTimes.add(now)
    }

    fun onPayeeChange(old: String, new: String, now: Long) {
        if (!active) return
        touched = true
        if (new.length - old.length >= PASTE_MIN_CHARS && '@' in new) {
            pasted = true
            pastedSecondsAfterReturn = if (returnedAt > 0) seconds(now - returnedAt) else null
        }
    }

    /** A saved payee was picked: nothing was typed or pasted. */
    fun onPayeePicked() {
        if (active) touched = true
        pasted = false
        pastedSecondsAfterReturn = null
    }

    fun onBackground(now: Long) {
        if (!active || paid || backgroundAt > 0) return
        backgroundAt = now
        switches++
    }

    fun onForeground(now: Long) {
        if (backgroundAt == 0L) return
        awayMs += now - backgroundAt
        backgroundAt = 0
        returnedAt = now
    }

    /** The user tapped Pay: this flow is done and is not "abandoned". */
    fun markPaid() {
        paid = true
    }

    /** Median seconds between digit presses, or null with fewer than two digits. */
    fun medianGapSeconds(): Double? {
        val gaps = digitTimes.zipWithNext { a, b -> b - a }
        if (gaps.isEmpty()) return null
        val s = gaps.sorted()
        val mid = s.size / 2
        val ms = if (s.size % 2 == 1) s[mid].toDouble() else (s[mid - 1] + s[mid]) / 2.0
        return round1(ms / 1000.0)
    }

    /**
     * The `session` object for this payment at the moment of Pay. [usualGaps] are this user's
     * median gaps from earlier completed payments; with fewer than three the comparison is unknown.
     */
    fun toSignal(now: Long, usualGaps: List<Double>): SessionSignal {
        while (abandonedAt.isNotEmpty() && now - abandonedAt.first() > ABANDON_WINDOW_MS) abandonedAt.removeFirst()
        val median = medianGapSeconds()
        val maxGap = digitTimes.zipWithNext { a, b -> b - a }.maxOrNull()?.let { seconds(it) }
        val usual = usualGaps.takeLast(BASELINE_KEEP).takeIf { it.size >= BASELINE_MIN }?.let(::median)
        val stillAway = if (backgroundAt > 0) now - backgroundAt else 0
        return SessionSignal(
            amountDigits = digitTimes.size,
            amountMedianGapS = median,
            amountMaxGapS = maxGap,
            amountGapVsUsual = if (median != null && usual != null && usual > 0) round1(median / usual) else null,
            amountEdits = edits,
            payeePasted = pasted,
            pastedWithinSOfReturn = pastedSecondsAfterReturn,
            appSwitches = switches,
            awayS = seconds(awayMs + stillAway),
            payScreenS = seconds(now - startedAt),
            abandonedFlows30m = abandonedAt.size,
        )
    }

    companion object {
        const val PASTE_MIN_CHARS = 5
        const val ABANDON_WINDOW_MS = 30 * 60_000L
        const val BASELINE_MIN = 3
        const val BASELINE_KEEP = 10

        private fun seconds(ms: Long) = round1(ms / 1000.0)
        private fun round1(x: Double) = round(x * 10) / 10
        private fun median(xs: List<Double>): Double {
            val s = xs.sorted()
            val mid = s.size / 2
            return if (s.size % 2 == 1) s[mid] else (s[mid - 1] + s[mid]) / 2
        }
    }
}
