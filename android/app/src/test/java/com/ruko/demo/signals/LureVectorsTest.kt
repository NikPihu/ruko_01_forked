package com.ruko.demo.signals

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.File

/**
 * Scores every text in ml/model/artifacts/lure_vectors.json with the app's copy of lure.json
 * (ml/PLAN.md §12): probabilities agree with Python to 1e-6, tags exactly.
 */
class LureVectorsTest {

    private val repo: File = generateSequence(File("").absoluteFile) { it.parentFile }
        .first { File(it, "ml/model/artifacts/lure_vectors.json").exists() }
    private val json = Json { ignoreUnknownKeys = true }

    private val model = json.decodeFromString(
        LureModel.serializer(),
        File(repo, "android/app/src/main/assets/lure.json").readText(),
    )
    private val classifier = LinearLureClassifier(model)
    private val vectors = Json.parseToJsonElement(File(repo, "ml/model/artifacts/lure_vectors.json").readText()).jsonObject

    @Test
    fun assetIsTheTrainedModel() {
        val trained = json.decodeFromString(LureModel.serializer(), File(repo, "ml/model/artifacts/lure.json").readText())
        assertEquals(trained, model)
        assertEquals(vectors["classes"]!!.jsonArray.map { it.jsonPrimitive.content }, model.classes)
    }

    @Test
    fun everyVectorMatchesPython() {
        val cases = vectors["vectors"]!!.jsonArray
        check(cases.isNotEmpty())
        for (case in cases.map { it.jsonObject }) {
            val text = case["text"]!!.jsonPrimitive.content
            val probs = classifier.probabilities(text)
            val expected = case["probs"]!!.jsonArray.map { it.jsonPrimitive.double }
            assertEquals(text, expected.size, probs.size)
            expected.zip(probs).forEach { (e, p) -> assertEquals(text, e, p, 1e-6) }

            // Top class (the old rule), then the phone's rule: best scam tag at 1 - P(normal).
            val top = probs.indices.maxBy { probs[it] }
            assertEquals(text, case["tag"]!!.jsonPrimitive.content, model.classes[top])
            val hit = classifier.classify(text)
            assertEquals(text, case["scam_tag"]!!.jsonPrimitive.content, hit.tag)
            assertEquals(text, case["scam_conf"]!!.jsonPrimitive.double, hit.conf, 1e-6)
        }
    }

    @Test
    fun noBreakSpaceSplitsWords() {
        assertEquals(charWbNgrams("a b", 3, 3), charWbNgrams("a b", 3, 3))
    }
}
