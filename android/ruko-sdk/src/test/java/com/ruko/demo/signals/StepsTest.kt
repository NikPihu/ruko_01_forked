package com.ruko.demo.signals

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.File

/**
 * The phone's scam steps (c2-0.14) must equal Python's backend/features/steps.py phone_steps on
 * contracts/examples/steps_vectors.json, and assets/steps.json must be the contract's steps.json.
 */
class StepsTest {
    private val repo: File = generateSequence(File("").absoluteFile) { it.parentFile }
        .first { File(it, "contracts/steps.json").exists() }
    private val contractText = File(repo, "contracts/steps.json").readText()
    private val vocab = StepVocab.parse(contractText)
    private val cases = Json.parseToJsonElement(File(repo, "contracts/examples/steps_vectors.json").readText())
        .jsonObject.getValue("cases").jsonArray

    @Test
    fun theAppsCopyIsTheContractsVocabulary() {
        val asset = File(repo, "android/ruko-sdk/src/main/assets/steps.json").readText()
        assertEquals(Json.parseToJsonElement(contractText), Json.parseToJsonElement(asset))
    }

    @Test
    fun stepsMatchPython() {
        assertEquals(true, cases.size >= 50)
        for (c in cases) {
            val o = c.jsonObject
            val name = o.getValue("case").jsonPrimitive.content
            val features = o.getValue("features").jsonObject.mapValues { (_, x) -> if (x is JsonNull) null else x.jsonPrimitive.double }
            val got = Steps.phoneSteps(features, vocab)
            val want = o.getValue("steps").jsonObject
            assertEquals("$name: step names", want.keys, got.keys)
            for ((step, pair) in want) {
                val (seen, ago) = pair.jsonArray
                assertEquals("$name: $step seen", if (seen is JsonNull) null else seen.jsonPrimitive.boolean, got.getValue(step).seen)
                assertEquals("$name: $step min_ago", if (ago is JsonNull) null else ago.jsonPrimitive.double, got.getValue(step).minAgo)
            }
        }
    }

    @Test
    fun verdictStepsKeepVocabularyOrder() {
        val features = mapOf("dev_call_active" to 1.0, "dev_call_voip" to 1.0, "dev_call_minutes" to 20.0, "dev_first_time_payee" to 1.0)
        val (seen, unmeasured) = Steps.verdictSteps(features, vocab)
        assertEquals(listOf("unknown_call", "voip_call", "long_call", "new_payee"), seen.map { it.first })
        assertEquals(0.0, seen.first().second)
        assertEquals(true, "dictated_amount" in unmeasured && "remote_control" in unmeasured)
    }
}
