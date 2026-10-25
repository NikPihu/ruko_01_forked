package com.ruko.demo.shield

import com.ruko.demo.net.EpisodeSignal
import com.ruko.demo.net.RukoJson
import com.ruko.demo.signals.BankSms
import com.ruko.demo.signals.Flow
import com.ruko.demo.signals.MoneyTxn
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.time.OffsetDateTime

/**
 * Runs contracts/examples/episode_vectors.json, the same cases backend/tests/test_episode.py runs,
 * so the phone and the server always agree on what an episode is.
 */
class EpisodeTrackerTest {

    private val contracts: File = generateSequence(File("").absoluteFile) { it.parentFile }
        .map { File(it, "contracts") }
        .first { File(it, "episode_rules.json").exists() }

    private val json = Json { ignoreUnknownKeys = true }
    private val rules = json.decodeFromString(EpisodeRules.serializer(), File(contracts, "episode_rules.json").readText())
    private val vectors = Json.parseToJsonElement(File(contracts, "examples/episode_vectors.json").readText()).jsonObject
    private val base = OffsetDateTime.parse(vectors.getValue("base_ts").jsonPrimitive.content).toInstant().toEpochMilli()

    @Test
    fun assetCopyMatchesTheContract() {
        val asset = generateSequence(File("").absoluteFile) { it.parentFile }
            .map { File(it, "ruko-sdk/src/main/assets/episode_rules.json") }
            .firstOrNull { it.exists() } ?: File(contracts.parentFile, "android/ruko-sdk/src/main/assets/episode_rules.json")
        assertEquals(rules, json.decodeFromString(EpisodeRules.serializer(), asset.readText()))
        assertEquals(vectors.getValue("rules_version").jsonPrimitive.content, rules.version)
    }

    @Test
    fun everyVectorMatches() {
        val failures = mutableListOf<String>()
        for (v in vectors.getValue("vectors").jsonArray.map { it.jsonObject }) {
            val name = v.getValue("name").jsonPrimitive.content
            val got = encode(run(v))
            for ((field, want) in v.getValue("expect").jsonObject) {
                val have = got[field] ?: JsonNull
                if (!same(field, want, have)) failures += "$name: $field want $want got $have"
            }
        }
        assertTrue(failures.joinToString("\n"), failures.isEmpty())
    }

    @Test
    fun escalationCountsOnlyTheLatestRun() {
        assertEquals(0, escalationSteps(emptyList()))
        assertEquals(2, escalationSteps(listOf(1_500.0, 3_000.0, 6_500.0)))
        assertEquals(1, escalationSteps(listOf(5_000.0, 1_000.0, 2_000.0)))
        assertEquals(0, escalationSteps(listOf(1_000.0, 1_200.0)))
    }

    @Test
    fun stateSurvivesASaveAndLoad() {
        val tr = EpisodeTracker(rules, smsRead = true)
        tr.add(MoneyTxn(base, 150.0, Flow.IN, "task.reward1@ybl", fromSms = true))
        val restored = json.decodeFromString(WatcherState.serializer(), json.encodeToString(WatcherState.serializer(), tr.state))
        assertEquals(EpisodeState.WATCHING, EpisodeTracker(rules, true, restored).episode.state)
    }

    private fun run(v: JsonObject): EpisodeSignal {
        val tr = EpisodeTracker(rules, smsRead = v.getValue("sms_read").jsonPrimitive.boolean)
        val events = v.getValue("events").jsonArray.map { it.jsonObject }.sortedBy { it.getValue("at_h").jsonPrimitive.double }
        for (e in events) {
            val ts = at(e.getValue("at_h").jsonPrimitive.double)
            when {
                "sms" in e -> {
                    val sms = e.getValue("sms").jsonObject
                    // Release rules: a numbered sender is never a bank.
                    if (BankSms.trustedSender(sms.getValue("from").jsonPrimitive.content)) {
                        BankSms.parse(sms.getValue("body").jsonPrimitive.content, ts)?.let(tr::add)
                    }
                }
                "app" in e -> {
                    val app = e.getValue("app").jsonObject
                    tr.add(MoneyTxn(ts, app.getValue("amount").jsonPrimitive.double, Flow.OUT, app.getValue("to").jsonPrimitive.content.lowercase()))
                }
                "dismiss" in e -> tr.dismiss(ts)
            }
        }
        return tr.summary(at(v.getValue("now_h").jsonPrimitive.double), v["payee"]?.jsonPrimitive?.content)
    }

    private fun at(hours: Double) = base + (hours * 3_600_000).toLong()

    private fun encode(s: EpisodeSignal): JsonObject =
        RukoJson.parseToJsonElement(RukoJson.encodeToString(EpisodeSignal.serializer(), s)).jsonObject

    private fun same(field: String, want: JsonElement, have: JsonElement): Boolean {
        if (want is JsonNull || have is JsonNull) return want is JsonNull && have is JsonNull
        val w = want.jsonPrimitive
        val h = have.jsonPrimitive
        if (w.isString || h.isString) return w.content == h.content
        if (w.content == "true" || w.content == "false") return w.content == h.content
        val tol = if (field == "age_days" || field == "out_to_in_ratio") 0.01 else 1e-9
        return kotlin.math.abs(w.double - h.double) <= tol
    }
}
