package com.ruko.demo.signals

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * The phone's lure model (lure-0.2) must score like Python (ml/model/lure_train.py `score_json` +
 * `decide`) on every case in ml/model/artifacts/lure_vectors.json, including its temperature and
 * the "unclear" rule, and the shipped asset must be the trained model.
 */
class LureModelTest {
    private val repo: File = generateSequence(File("").absoluteFile) { it.parentFile }
        .first { File(it, "ml/model/artifacts/lure_vectors.json").exists() }
    private val artifacts = File(repo, "ml/model/artifacts")
    private val assets = File(repo, "android/ruko-sdk/src/main/assets")
    private val model = Json { ignoreUnknownKeys = true }.decodeFromString(LureModel.serializer(), File(artifacts, "lure.json").readText())
    private val classifier = LinearLureClassifier(model)
    private val vectorFile = Json.parseToJsonElement(File(artifacts, "lure_vectors.json").readText()).jsonObject

    @Test
    fun theModelIsLure02WithItsCalibration() {
        assertEquals("lure-0.2", model.version)
        assertEquals(listOf("arrest_threat", "kyc", "normal", "other_scam", "refund", "task_job", "trading_tip"), model.classes)
        assertEquals(LURE_SEND_THRESHOLD, model.unclearBelow, 0.0)
        assertEquals(vectorFile.getValue("temperature").jsonPrimitive.double, model.temperature, 0.0)
        assertTrue(model.temperature != 1.0)
    }

    @Test
    fun everyVectorGetsPythonsAnswer() {
        val vectors = vectorFile.getValue("vectors").jsonArray
        assertTrue(vectors.isNotEmpty())
        val tags = HashSet<String>()
        for (v in vectors) {
            val o = v.jsonObject
            val text = o.getValue("text").jsonPrimitive.content
            val hit = classifier.classify(text)
            assertEquals(text, o.getValue("tag").jsonPrimitive.content, hit.tag)
            assertEquals(text, o.getValue("top").jsonPrimitive.content, hit.top)
            assertEquals(text, o.getValue("conf").jsonPrimitive.double, hit.conf, 2e-6)
            val probs = classifier.probabilities(text)
            o.getValue("probs").jsonArray.forEachIndexed { i, p -> assertEquals(text, p.jsonPrimitive.double, probs[i], 2e-6) }
            tags += hit.tag
        }
        // The vectors must exercise the new class and the unclear decision.
        assertTrue(tags.toString(), LURE_UNCLEAR in tags && "other_scam" in tags && LURE_NORMAL in tags)
    }

    @Test
    fun unclearWhenNoClassReachesTheThreshold() {
        val classes = listOf("arrest_threat", "kyc", "normal", "other_scam", "refund", "task_job", "trading_tip")
        val decided = LinearLureClassifier.decide(classes, listOf(0.7, 0.05, 0.1, 0.05, 0.05, 0.03, 0.02))
        assertEquals(LureHit("arrest_threat", 0.7, top = "arrest_threat"), decided)
        assertTrue(decided.scam)
        // Exactly 0.6 is decided.
        assertEquals("normal", LinearLureClassifier.decide(classes, listOf(0.0, 0.0, 0.6, 0.4, 0.0, 0.0, 0.0)).tag)
        // Below 0.6 the answer is unclear and keeps what it leaned to.
        val unsure = LinearLureClassifier.decide(classes, listOf(0.05, 0.35, 0.3, 0.0, 0.3, 0.0, 0.0))
        assertEquals(LURE_UNCLEAR, unsure.tag)
        assertEquals("kyc", unsure.top)
        assertEquals(0.35, unsure.conf, 0.0)
        assertTrue(unsure.unclear)
        assertFalse(unsure.scam)
        // Leaning to normal is still unclear, never normal (rule 1).
        val leaningNormal = LinearLureClassifier.decide(classes, listOf(0.1, 0.1, 0.59, 0.1, 0.11, 0.0, 0.0))
        assertEquals(LURE_UNCLEAR, leaningNormal.tag)
        assertEquals("normal", leaningNormal.top)
        // Ties go to the first class, like Python.
        assertEquals("arrest_threat", LinearLureClassifier.decide(classes, listOf(0.3, 0.3, 0.2, 0.2, 0.0, 0.0, 0.0)).top)
    }

    @Test
    fun temperatureSoftensWithoutChangingTheRanking() {
        val base = LureModel(
            version = "t", ngramRange = listOf(2, 3), classes = listOf("kyc", "normal"), vocabulary = mapOf(" k" to 0),
            idf = listOf(1.0), coef = listOf(listOf(2.0), listOf(-2.0)), intercept = listOf(0.0, 0.0),
        )
        val plain = LinearLureClassifier(base).probabilities("kyc")
        val soft = LinearLureClassifier(base.copy(temperature = 4.0)).probabilities("kyc")
        assertEquals(1 / (1 + kotlin.math.exp(-4.0)), plain[0], 1e-12)
        assertEquals(1 / (1 + kotlin.math.exp(-1.0)), soft[0], 1e-12)
        assertEquals("kyc", LinearLureClassifier(base.copy(temperature = 4.0)).classify("kyc").tag)
    }

    @Test
    fun onlyScamTagsAreScams() {
        assertTrue(isScamTag("other_scam") && isScamTag("kyc"))
        assertFalse(isScamTag(LURE_NORMAL))
        assertFalse(isScamTag(LURE_UNCLEAR))
        assertEquals(
            listOf("other_scam"),
            bestLureTags(listOf(LureHit("other_scam", 0.8), LureHit(LURE_UNCLEAR, 0.59, top = "kyc"), LureHit("normal", 0.99))).map { it.tag },
        )
    }

    @Test
    fun shippedAssetsAreTheTrainedModels() {
        assertEquals(File(artifacts, "lure.json").readText(), File(assets, "lure.json").readText())
        assertEquals(File(artifacts, "v0/device_model.json").readText(), File(assets, "device_model.json").readText())
    }
}
