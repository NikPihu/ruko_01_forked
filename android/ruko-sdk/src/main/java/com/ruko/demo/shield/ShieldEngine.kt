package com.ruko.demo.shield

import com.ruko.demo.signals.Flow
import com.ruko.demo.signals.MoneyTxn
import kotlinx.serialization.Serializable

/**
 * What the background watcher does with new transactions, without any Android code:
 * update the episode, pick the notifications to show (one per new state of the episode, and one per
 * payment made in another app during it; no weekly cap) and record state changes, which become
 * episode events for the server (c2-0.4).
 * WATCHING (small money from a stranger) is recorded but never shown: one credit is too common
 * (refunds, cashback) to warn about. The user hears from us once the pattern is ACTIVE.
 */
object ShieldEngine {

    enum class AlertKind { ACTIVE, OUT_OTHER_APP }

    data class Alert(val kind: AlertKind, val episodeId: String?, val amountInr: Double, val summary: EpisodeSummaryText)

    /** The numbers a notification or the Alerts card puts into words. */
    data class EpisodeSummaryText(val baitCredits: Int, val baitInr: Double, val outs: Int, val outsInr: Double, val newPayees: Int)

    /** A state change (§8.1 trigger) with the transaction that caused it, if any. */
    @Serializable
    data class Transition(val trigger: String, val episodeId: String?, val ts: Long, val txn: MoneyTxn? = null)

    /** [fresh]: the transactions this call took as new (a repeated alert is not), oldest first. */
    data class Result(val data: ShieldData, val alerts: List<Alert>, val transitions: List<Transition>, val fresh: List<MoneyTxn> = emptyList())

    private const val SAME_ALERT_MS = 2 * 60_000L
    private const val WEEK_MS = 7 * 86_400_000L

    fun apply(rules: EpisodeRules, smsRead: Boolean, data: ShieldData, txns: List<MoneyTxn>, now: Long): Result {
        val tr = EpisodeTracker(rules, smsRead, data.watcher)
        val alerts = ArrayList<Alert>()
        val transitions = ArrayList<Transition>()
        // The SMS receiver and the catch-up scan can both see the same alert; keep the first.
        val fresh = txns.filter { t -> data.watcher.history.none { h -> sameAlert(h, t) } }
            .distinctBy { listOf(it.flow, it.amount, it.counterparty, it.fromSms, it.ts / SAME_ALERT_MS) }.sortedBy { it.ts }
        for (t in fresh) {
            val before = tr.episode
            tr.add(t)
            diff(before, tr.episode, t, t.ts, transitions, alerts)
        }
        val before = tr.episode
        tr.summary(now) // closes a quiet episode
        diff(before, tr.episode, null, now, transitions, alerts)
        return finish(data, tr, alerts, transitions, now).copy(fresh = fresh)
    }

    /** The user tapped "I know them / it's a real job". */
    fun dismiss(rules: EpisodeRules, smsRead: Boolean, data: ShieldData, now: Long): Result {
        val tr = EpisodeTracker(rules, smsRead, data.watcher)
        val before = tr.episode
        tr.dismiss(now)
        val transitions = if (before.state.live && tr.episode.state == EpisodeState.DISMISSED) {
            listOf(Transition("dismissed", before.id, now))
        } else {
            emptyList()
        }
        return Result(data.copy(watcher = tr.state, serverRisk = null, serverMessageKey = null), emptyList(), transitions)
    }

    private fun diff(before: Episode, after: Episode, t: MoneyTxn?, ts: Long, transitions: MutableList<Transition>, alerts: MutableList<Alert>) {
        val sameEpisode = before.id != null && before.id == after.id
        if (before.state.live && !sameEpisode) transitions += Transition("closed", before.id, ts)
        if (after.state == EpisodeState.WATCHING && !(sameEpisode && before.state.live)) {
            transitions += Transition("watching", after.id, ts, t)
            return
        }
        if (!sameEpisode || t == null) return
        if (before.state == EpisodeState.WATCHING && after.state == EpisodeState.ACTIVE) {
            transitions += Transition("active", after.id, ts, t)
            alerts += Alert(AlertKind.ACTIVE, after.id, t.amount, text(after))
            return
        }
        if (after.state.live && t.flow == Flow.IN && after.bait.size > before.bait.size) {
            val newSender = t.counterparty != null && before.bait.none { it.counterparty == t.counterparty }
            if (newSender) transitions += Transition("bait", after.id, ts, t)
        }
        if (before.state == EpisodeState.ACTIVE && after.outs.size > before.outs.size) {
            transitions += Transition("out_payment", after.id, ts, t)
            if (t.fromSms) alerts += Alert(AlertKind.OUT_OTHER_APP, after.id, t.amount, text(after))
        }
    }

    private fun finish(data: ShieldData, tr: EpisodeTracker, alerts: List<Alert>, transitions: List<Transition>, now: Long): Result {
        var notified = data.notified.filter { now - it.ts <= WEEK_MS }
        val shown = ArrayList<Alert>()
        for (a in alerts) {
            val key = "${a.episodeId}:${a.kind}" + if (a.kind == AlertKind.OUT_OTHER_APP) ":${a.amountInr}" else ""
            if (notified.any { it.key == key }) continue // already told: not a new alert
            notified = notified + Notified(now, key)
            shown += a
        }
        val closed = tr.episode.state == EpisodeState.NONE
        return Result(
            data.copy(
                watcher = tr.state,
                notified = notified,
                serverRisk = if (closed) null else data.serverRisk,
                serverMessageKey = if (closed) null else data.serverMessageKey,
            ),
            shown,
            transitions,
        )
    }

    private fun sameAlert(a: MoneyTxn, b: MoneyTxn) = a.fromSms == b.fromSms && a.flow == b.flow &&
        a.amount == b.amount && a.counterparty == b.counterparty && kotlin.math.abs(a.ts - b.ts) <= SAME_ALERT_MS

    private fun text(ep: Episode) = EpisodeSummaryText(
        baitCredits = ep.bait.size,
        baitInr = ep.bait.sumOf { it.amount },
        outs = ep.outs.size,
        outsInr = ep.outs.sumOf { it.amount },
        newPayees = (ep.outs.mapNotNull { it.counterparty }.toSet() - ep.paidBefore).size + ep.outs.count { it.counterparty == null },
    )
}
