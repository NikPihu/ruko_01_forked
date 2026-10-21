package com.ruko.demo.shield

import com.ruko.demo.net.EpisodeSignal
import com.ruko.demo.signals.Flow
import com.ruko.demo.signals.MoneyTxn
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlin.math.abs
import kotlin.math.roundToLong

/**
 * Task-scam episode: the same state machine as backend/features/episode.py.
 *
 *     NONE --bait credit--> WATCHING --2+ outs to new payees and 2+ escalation steps--> ACTIVE
 *     WATCHING / ACTIVE --30 days with no bait and no out to a new payee--> NONE
 *     WATCHING / ACTIVE --"I know them / real job"--> DISMISSED
 *     DISMISSED --a NEW bait sender--> WATCHING (fresh episode); --30 days--> NONE
 *
 * Only payments above min_out_inr to payees the user had not paid before the episode are "outs":
 * the scam is paying strangers to "unlock" earnings, and counting the usual shop, the landlord or a
 * ₹100 snack would turn everyday spending into escalation.
 *
 * Pure Kotlin (no Android imports) so EpisodeTrackerTest can run contracts/examples/episode_vectors.json.
 * Thresholds come from assets/episode_rules.json, a copy of contracts/episode_rules.json.
 */

@Serializable
data class EpisodeRules(
    val version: String,
    @SerialName("bait_max_inr") val baitMaxInr: Double,
    @SerialName("min_out_inr") val minOutInr: Double,
    @SerialName("escalation_factor") val escalationFactor: Double,
    @SerialName("active_min_outs") val activeMinOuts: Int,
    @SerialName("active_min_escalation_steps") val activeMinEscalationSteps: Int,
    @SerialName("quiet_close_days") val quietCloseDays: Int,
    @SerialName("history_days") val historyDays: Int,
    @SerialName("same_payment_minutes") val samePaymentMinutes: Int,
)

@Serializable
enum class EpisodeState(val wire: String) {
    NONE("none"), WATCHING("watching"), ACTIVE("active"), DISMISSED("dismissed");

    val live: Boolean get() = this == WATCHING || this == ACTIVE
}

@Serializable
data class Episode(
    val id: String? = null, // stable for the whole episode (events in c2-0.4)
    val state: EpisodeState = EpisodeState.NONE,
    val startTs: Long? = null, // first bait credit
    val lastActivityTs: Long? = null,
    val dismissedTs: Long? = null,
    val bait: List<MoneyTxn> = emptyList(),
    val outs: List<MoneyTxn> = emptyList(),
    val knownSenders: Set<String> = emptySet(), // bait senders when dismissed
    val paidBefore: Set<String> = emptySet(), // payees paid before the episode started
)

/** Everything the watcher keeps (encrypted by EpisodeStore). */
@Serializable
data class WatcherState(
    val episode: Episode = Episode(),
    val history: List<MoneyTxn> = emptyList(), // counted transactions, history_days
)

class EpisodeTracker(
    private val rules: EpisodeRules,
    private val smsRead: Boolean,
    state: WatcherState = WatcherState(),
    private val newId: () -> String = { java.util.UUID.randomUUID().toString() },
) {
    var episode = state.episode
        private set
    private val history = state.history.toMutableList()

    val state: WatcherState get() = WatcherState(episode, history.toList())

    private val dayMs = 86_400_000L

    // ---------- input ----------

    fun add(t: MoneyTxn) {
        if (t.fromSms && !smsRead) return
        expire(t.ts)
        if (duplicate(t)) return
        history += t
        if (t.flow == Flow.IN) {
            if (isBait(t)) onBait(t)
        } else {
            onOut(t)
        }
    }

    fun dismiss(ts: Long) {
        expire(ts)
        if (episode.state.live) {
            episode = Episode(
                id = episode.id,
                state = EpisodeState.DISMISSED,
                dismissedTs = ts,
                knownSenders = episode.bait.mapNotNull { it.counterparty }.toSet(),
            )
        }
    }

    /** Drop everything (the user switched the watcher off or deleted the history). */
    fun clear() {
        episode = Episode()
        history.clear()
    }

    // ---------- rules ----------

    private fun paid(beforeTs: Long): Set<String> =
        history.filter { it.flow == Flow.OUT && it.counterparty != null && it.ts < beforeTs }.mapNotNull { it.counterparty }.toSet()

    private fun isBait(t: MoneyTxn): Boolean =
        t.amount <= rules.baitMaxInr && (t.counterparty == null || t.counterparty !in paid(t.ts))

    private fun onBait(t: MoneyTxn) {
        var ep = episode
        if (ep.state == EpisodeState.DISMISSED) {
            if (t.counterparty == null || t.counterparty in ep.knownSenders) return
            ep = Episode()
        }
        if (ep.state == EpisodeState.NONE) {
            ep = Episode(id = newId(), state = EpisodeState.WATCHING, startTs = t.ts, paidBefore = paid(t.ts))
        }
        episode = ep.copy(bait = ep.bait + t, lastActivityTs = t.ts)
    }

    private fun onOut(t: MoneyTxn) {
        val ep = episode
        if (!ep.state.live || t.amount <= rules.minOutInr || (t.counterparty != null && t.counterparty in ep.paidBefore)) return
        val next = ep.copy(outs = ep.outs + t, lastActivityTs = t.ts)
        val becomesActive = next.state == EpisodeState.WATCHING &&
            newPayeeOuts(next) >= rules.activeMinOuts &&
            escalationSteps(next.outs.map { it.amount }, rules.escalationFactor) >= rules.activeMinEscalationSteps
        episode = if (becomesActive) next.copy(state = EpisodeState.ACTIVE) else next
    }

    // An out with no named payee (some bank alerts) counts as a new payee: unknown is not safe.
    private fun newPayeeOuts(ep: Episode): Int = ep.outs.count { it.counterparty == null || it.counterparty !in ep.paidBefore }

    /** A payment made in this app also arrives as a debit SMS; count it once. */
    private fun duplicate(t: MoneyTxn): Boolean {
        val win = rules.samePaymentMinutes * 60_000L
        return history.any { h -> h.flow == t.flow && h.amount == t.amount && abs(h.ts - t.ts) <= win && h.fromSms != t.fromSms }
    }

    private fun expire(now: Long) {
        history.removeAll { now - it.ts > rules.historyDays * dayMs }
        val quiet = rules.quietCloseDays * dayMs
        val ep = episode
        if (ep.state.live && now - (ep.lastActivityTs ?: now) >= quiet) episode = Episode()
        if (ep.state == EpisodeState.DISMISSED && now - (ep.dismissedTs ?: now) >= quiet) episode = Episode()
    }

    // ---------- output ----------

    /** The `context.episode` object (c2-0.3). Null means unknown, never zero. */
    fun summary(now: Long, payee: String? = null): EpisodeSignal {
        expire(now)
        val ep = episode
        val live = ep.state.live
        val outs = if (live) ep.outs else emptyList()
        val baitInr = if (live) ep.bait.sumOf { it.amount } else 0.0
        val outsInr = outs.sumOf { it.amount }
        val named = outs.mapNotNull { it.counterparty }.toSet()
        return EpisodeSignal(
            state = ep.state.wire,
            ageDays = if (live) round3((now - ep.startTs!!) / dayMs.toDouble()) else null,
            baitCredits = if (smsRead) (if (live) ep.bait.size else 0) else null,
            baitInr = if (smsRead) baitInr else null,
            outs = outs.size,
            outsInr = outsInr,
            newPayees = (named - ep.paidBefore).size + outs.count { it.counterparty == null },
            escalationSteps = escalationSteps(outs.map { it.amount }, rules.escalationFactor),
            lastOutInr = outs.lastOrNull()?.amount,
            outToInRatio = if (smsRead && baitInr > 0) round2(outsInr / baitInr) else null,
            payeeSeenInEpisode = if (payee != null && live) payee.trim().lowercase() in named else null,
            rulesVersion = rules.version,
        )
    }

    private fun round3(x: Double) = (x * 1000).roundToLong() / 1000.0
    private fun round2(x: Double) = (x * 100).roundToLong() / 100.0
}

/** How many payments in a row, ending with the latest, were each >= factor x the one before. */
fun escalationSteps(amounts: List<Double>, factor: Double = 1.5): Int {
    var steps = 0
    for (i in amounts.lastIndex downTo 1) {
        if (amounts[i] >= factor * amounts[i - 1]) steps++ else break
    }
    return steps
}
