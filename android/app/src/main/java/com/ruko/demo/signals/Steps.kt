package com.ruko.demo.signals

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.math.floor

/**
 * Scam steps the phone can see (contract c2-0.14, `device_verdict.steps_seen`), in the shared vocabulary
 * contracts/steps.json (copied to assets/steps.json; StepsTest checks the copy). A line-by-line port of
 * backend/features/steps.py `phone_steps`; contracts/examples/steps_vectors.json holds Python's answers.
 *
 * A step is true (seen), false (measured, not seen) or null (not measured). Null is never false (rule 1).
 */
class StepVocab(
    val version: String,
    val ids: List<String>,
    private val params: JsonObject,
) {
    fun p(name: String): Double = params.getValue(name).jsonPrimitive.double
    fun session(name: String): Double = params.getValue("session").jsonObject.getValue(name).jsonPrimitive.double

    companion object {
        fun parse(text: String): StepVocab {
            val o = Json.parseToJsonElement(text).jsonObject
            return StepVocab(
                o.getValue("version").jsonPrimitive.content,
                o.getValue("steps").jsonArray.map { it.jsonObject.getValue("id").jsonPrimitive.content },
                o.getValue("params").jsonObject,
            )
        }
    }
}

/** One step's reading: seen (true / false / null) and, when seen, how many minutes ago. */
data class StepReading(val seen: Boolean?, val minAgo: Double?)

object Steps {
    private val DEV_LURE = linkedMapOf(
        "arrest_threat" to "dev_lure_arrest", "kyc" to "dev_lure_kyc", "task_job" to "dev_lure_task",
        "trading_tip" to "dev_lure_trading", "refund" to "dev_lure_refund", "other_scam" to "dev_lure_other_scam",
    )

    /** Half up to one decimal, the same in Python (math.floor(x * 10 + 0.5) / 10). */
    fun round1(x: Double): Double = floor(x * 10 + 0.5) / 10

    private fun on(x: Double?): Boolean? = x?.let { it >= 0.5 }
    private fun ge(x: Double?, t: Double): Boolean? = x?.let { it >= t }

    /** Three-valued AND: false if any is false, else null if any is null, else true. */
    private fun and(vararg xs: Boolean?): Boolean? = when {
        xs.any { it == false } -> false
        xs.any { it == null } -> null
        else -> true
    }

    private fun or(vararg xs: Boolean?): Boolean? = when {
        xs.any { it == true } -> true
        xs.any { it == null } -> null
        else -> false
    }

    /** {step: reading} for every step the phone can measure, from its device features (DeviceFeatures). */
    fun phoneSteps(f: Map<String, Double?>, v: StepVocab): Map<String, StepReading> {
        val out = LinkedHashMap<String, Pair<Boolean?, Double?>>()
        val active = on(f["dev_call_active"])
        val ended = f["dev_call_ended_min_ago"]
        val recent: Boolean? = if (active == null) null else (active || (ended != null && ended <= v.p("recent_call_min")))
        val callAgo: Double? = if (recent != true) null else if (active == true) 0.0 else ended
        val voip = on(f["dev_call_voip"])
        // A VoIP call never shows its number: contact status unknown counts as an unknown caller.
        var unknown = on(f["dev_call_unknown"])
        if (unknown == null && voip == true) unknown = true
        out["unknown_call"] = and(recent, unknown) to callAgo
        out["voip_call"] = and(recent, voip) to callAgo
        val incoming = on(f["dev_call_incoming"])
        out["call_out_to_unknown"] = and(out.getValue("unknown_call").first, incoming?.let { !it }) to callAgo
        out["long_call"] = and(recent, ge(f["dev_call_minutes"], v.p("long_call_min"))) to callAgo
        out["foreign_call"] = and(recent, on(f["dev_call_foreign"])) to callAgo

        val lureAgo = f["dev_lure_min_ago"]
        for ((tag, name) in DEV_LURE) {
            if (f.containsKey(name) || tag != "other_scam") {
                val seen = ge(f[name], v.p("lure_min_conf"))
                out["lure:$tag"] = seen to (if (seen == true) lureAgo else null)
            }
        }
        if (f.containsKey("dev_lure_unclear")) {
            val seen = on(f["dev_lure_unclear"])
            out["lure:unclear"] = seen to (if (seen == true) lureAgo else null)
        }

        val state = f["dev_ep_state"]
        out["bait_credit"] = ge(f["dev_ep_bait_credits"], 1.0) to null
        out["episode_watching"] = state?.let { it == 1.0 } to null
        out["episode_active"] = state?.let { it == 2.0 } to null
        out["escalating_payments"] = ge(f["dev_ep_escalation"], 1.0) to null

        val rec = on(f["dev_screen_recorded"])
        val rmin = f["dev_remote_min_ago"]
        val remoteRecent: Boolean? = if (f["dev_remote_installed"] == null) null else (rmin != null && rmin <= v.p("remote_recent_min"))
        out["remote_control"] = or(rec, remoteRecent) to null
        out["untrusted_accessibility"] = on(f["dev_accessibility"]) to null
        out["sideload_24h"] = on(f["dev_sideloaded_24h"]) to null

        val s = Session.of(f)
        if (s == null) {
            for (k in listOf("dictated_amount", "paste_after_switch", "many_app_switches", "long_hesitation", "abandoned_tries")) {
                out[k] = null to null
            }
        } else {
            out["dictated_amount"] = s.dictated(v) to 0.0
            out["paste_after_switch"] = s.pastedAfterSwitch(v) to 0.0
            out["many_app_switches"] = ge(s.appSwitches, v.p("many_app_switches")) to 0.0
            out["long_hesitation"] = s.hesitation(v) to 0.0
            out["abandoned_tries"] = ge(s.abandoned, 1.0) to null
        }

        val after: Boolean? = if (active == null) null else
            (!active && ended != null && ended >= v.p("after_call_min_from") && ended <= v.p("recent_call_min"))
        out["paid_after_call"] = and(after, unknown) to (if (after == true) ended else null)
        out["new_payee"] = on(f["dev_first_time_payee"]) to null
        out["amount_unusual"] = ge(f["dev_amount_to_max"], v.p("amount_unusual_vs_max")) to null
        return out.mapValues { (_, r) -> StepReading(r.first, if (r.first == true) r.second?.let(::round1) else null) }
    }

    /** The verdict's steps_seen (vocabulary order, with minutes ago) and steps_unmeasured. */
    fun verdictSteps(f: Map<String, Double?>, v: StepVocab): Pair<List<Pair<String, Double?>>, List<String>> {
        val ps = phoneSteps(f, v)
        val seen = v.ids.filter { ps[it]?.seen == true }.map { it to ps.getValue(it).minAgo }
        val unmeasured = v.ids.filter { it in ps && ps.getValue(it).seen == null }
        return seen to unmeasured
    }

    /** The Pay-screen numbers back from device features (backend/features/session.py signs, the same thresholds). */
    private class Session(
        val digits: Double?, val medianGap: Double?, val maxGap: Double?, val gapVsUsual: Double?,
        val pasted: Double?, val pastedAfterReturn: Double?, val appSwitches: Double?, val payScreen: Double?,
        val abandoned: Double?,
    ) {
        fun dictated(v: StepVocab): Boolean? {
            val d = digits ?: return null
            if (round(d) < v.session("dictated_min_digits")) return false
            gapVsUsual?.let { return it >= v.session("dictated_vs_usual") }
            if (medianGap == null || maxGap == null) return null
            return medianGap >= v.session("dictated_no_baseline_median_s") && maxGap >= v.session("dictated_no_baseline_max_s")
        }

        fun pastedAfterSwitch(v: StepVocab): Boolean? {
            val p = pasted ?: return null
            if (p < 0.5) return false
            val within = pastedAfterReturn ?: return if (appSwitches != null && round(appSwitches) == 0.0) false else null
            return within <= v.session("paste_after_return_s")
        }

        fun hesitation(v: StepVocab): Boolean? = payScreen?.let { it >= v.session("hesitation_s") }

        companion object {
            private val KEYS = listOf("dev_sess_digits", "dev_sess_median_gap_s", "dev_sess_max_gap_s", "dev_sess_gap_vs_usual",
                "dev_sess_edits", "dev_sess_pasted", "dev_sess_paste_after_return_s", "dev_sess_app_switches",
                "dev_sess_away_s", "dev_sess_pay_screen_s", "dev_sess_abandoned_30m")

            /** Python rounds the integer fields (int(round(v))): half to even, like Math.rint. */
            fun round(x: Double): Double = Math.rint(x)

            fun of(f: Map<String, Double?>): Session? {
                if (KEYS.all { f[it] == null }) return null
                return Session(f["dev_sess_digits"]?.let(::round), f["dev_sess_median_gap_s"], f["dev_sess_max_gap_s"],
                    f["dev_sess_gap_vs_usual"], f["dev_sess_pasted"], f["dev_sess_paste_after_return_s"],
                    f["dev_sess_app_switches"]?.let(::round), f["dev_sess_pay_screen_s"], f["dev_sess_abandoned_30m"]?.let(::round))
            }
        }
    }
}
