package com.ruko.demo.signals

import com.ruko.demo.net.LureSignal
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlin.math.exp
import kotlin.math.sqrt

/**
 * One scored message (lure-0.2). [tag] is a class of the model when its calibrated probability
 * reaches the 0.6 threshold, else [LURE_UNCLEAR]; [conf] is the probability of the most likely
 * class and [top] that class (equal to [tag] unless the answer is unclear), so callers can see what
 * an unclear message leaned to. Unclear is never reported as normal (rule 1).
 */
data class LureHit(val tag: String, val conf: Double, val minAgo: Double = 0.0, val top: String = tag) {
    val unclear: Boolean get() = tag == LURE_UNCLEAR

    /** A scam tag at or above the send threshold: what may leave the phone or warn the user. */
    val scam: Boolean get() = isScamTag(tag) && conf >= LURE_SEND_THRESHOLD
}

/** The model's everyday class and the decision for "no class reached 0.6". */
const val LURE_NORMAL = "normal"
const val LURE_UNCLEAR = "unclear"

/** Any tag that names a scam: every class but normal, and never unclear (not a class). */
fun isScamTag(tag: String): Boolean = tag != LURE_NORMAL && tag != LURE_UNCLEAR

interface LureClassifier {
    val version: String
    fun classify(text: String): LureHit
}

/** ml/model/artifacts/lure.json (guide format). */
@Serializable
data class LureModel(
    val version: String,
    val analyzer: String = "char_wb",
    @SerialName("ngram_range") val ngramRange: List<Int>,
    val lowercase: Boolean = true,
    val classes: List<String>,
    val vocabulary: Map<String, Int>,
    val idf: List<Double>,
    val coef: List<List<Double>>,
    val intercept: List<Double>,
    /** lure-0.2 calibration: probabilities are softmax(scores / temperature). */
    val temperature: Double = 1.0,
    /** No class at or above this probability: the answer is unclear (same number as the send threshold). */
    @SerialName("unclear_below") val unclearBelow: Double = LURE_SEND_THRESHOLD,
)

/**
 * Character n-gram TF-IDF + logistic regression, scored the way scikit-learn does, so a
 * message gets the same tag here as in Python:
 * char_wb n-grams → counts × idf → L2 norm → coef · v + intercept → softmax(scores / temperature),
 * then [decide] (ml/model/lure_train.py `score_json` + `decide`).
 */
class LinearLureClassifier(private val model: LureModel) : LureClassifier {
    override val version: String = model.version

    override fun classify(text: String): LureHit = decide(model.classes, probabilities(text), model.unclearBelow)

    /** The calibrated probability of each of the model's classes, in `classes` order. */
    fun probabilities(text: String): List<Double> {
        val counts = HashMap<Int, Int>()
        val input = if (model.lowercase) text.lowercase() else text
        for (gram in charWbNgrams(input, model.ngramRange[0], model.ngramRange[1])) {
            val index = model.vocabulary[gram] ?: continue
            counts[index] = (counts[index] ?: 0) + 1
        }
        val weights = counts.mapValues { (index, count) -> count * model.idf[index] }
        val norm = sqrt(weights.values.sumOf { it * it })
        val scores = model.coef.indices.map { k ->
            model.intercept[k] + if (norm == 0.0) 0.0 else weights.entries.sumOf { (i, w) -> model.coef[k][i] * w / norm }
        }
        // Two classes: scikit-learn keeps one row and uses the sigmoid for classes[1].
        if (scores.size == 1) {
            val p = 1.0 / (1.0 + exp(-scores[0] / model.temperature))
            return listOf(1.0 - p, p)
        }
        return softmax(scores.map { it / model.temperature })
    }

    companion object {
        /**
         * The phone's answer (ml/model/lure_train.py `decide`): the most likely class when its
         * probability reaches [unclearBelow] (0.6, the same for every class thanks to the
         * calibration), else [LURE_UNCLEAR] with that class as [LureHit.top] and its probability.
         * Ties go to the first class (Python does the same).
         */
        fun decide(classes: List<String>, probs: List<Double>, unclearBelow: Double = LURE_SEND_THRESHOLD): LureHit {
            val best = probs.indices.maxBy { probs[it] }
            val top = classes[best]
            return LureHit(if (probs[best] >= unclearBelow) top else LURE_UNCLEAR, probs[best], top = top)
        }
    }
}

/**
 * Fallback until lure.json arrives (guide: "keyword list per lure tag"). One keyword alone
 * scores below the 0.6 send threshold (an unclear hit), so a single word such as "refund" never flags a message.
 */
object KeywordLureClassifier : LureClassifier {
    override val version = "keywords-v1"

    private val keywords = mapOf(
        "arrest_threat" to listOf(
            "arrest", "cbi", "police", "warrant", "money laundering", "narcotics", "customs",
            "court", "fir ", "parcel", "drugs", "ed officer", "giraftar",
        ),
        "kyc" to listOf(
            "kyc", "pan card", "aadhaar", "blocked", "suspended", "update your", "verify your",
            "account will be", "expire", "re-kyc",
        ),
        "task_job" to listOf(
            "task", "part time", "work from home", "daily income", "earn", "like videos",
            "telegram", "salary", "per day", "rate products",
        ),
        "trading_tip" to listOf(
            "stock", "ipo", "trading", "profit", "returns", "shares", "investment", "guaranteed",
            "vip group", "crypto",
        ),
        "refund" to listOf(
            "refund", "cashback", "reversal", "scan qr", "receive money", "enter your upi pin", "collect request",
        ),
        "other_scam" to listOf(
            "electricity", "disconnected", "bill unpaid", "power cut", "lottery", "lucky draw", "prize",
            "processing fee", "redelivery", "e-challan", "gift card", "by mistake",
        ),
    )

    override fun classify(text: String): LureHit {
        val lower = text.lowercase()
        val (tag, hits) = keywords
            .map { (tag, words) -> tag to words.count { it in lower } }
            .maxBy { it.second }
        val conf = when (hits) {
            0 -> return LureHit(LURE_NORMAL, 1.0)
            1 -> return LureHit(LURE_UNCLEAR, 0.5, top = tag) // one word: leaning, not sure
            2 -> 0.7
            else -> 0.85
        }
        return LureHit(tag, conf)
    }
}

/** Only scam tags at or above this confidence leave the phone (guide step 5). */
const val LURE_SEND_THRESHOLD = 0.6

/** The tags to send: scam hits at or above the threshold (never normal or unclear), the strongest one per tag. */
fun bestLureTags(hits: List<LureHit>): List<LureHit> =
    hits.filter { it.scam }
        .groupBy { it.tag }
        .map { (_, sameTag) -> sameTag.maxBy { it.conf } }
        .sortedByDescending { it.conf }

fun LureHit.toLureSignal() = LureSignal(tag = tag, conf = round2(conf), minAgo = round1(minAgo.coerceAtLeast(0.0)))

private fun round2(value: Double) = kotlin.math.round(value * 100) / 100

private fun round1(value: Double) = kotlin.math.round(value * 10) / 10

// Python's str.split() whitespace, as scikit-learn uses (a no-break space splits words too).
// Spelled out because Android's regex engine (ICU) rejects the "(?U)" flag the JVM accepts.
private val WHITESPACE = Regex("[\\s\\p{Z}\\u001C-\\u001F\\u0085]+")

/**
 * scikit-learn's char_wb analyzer: each whitespace separated word is padded with one space
 * on each side, then cut into n-grams; a word shorter than n is counted once, whole.
 */
fun charWbNgrams(text: String, minN: Int, maxN: Int): List<String> {
    val out = ArrayList<String>()
    for (word in text.split(WHITESPACE).filter { it.isNotEmpty() }) {
        val w = " $word "
        for (n in minN..maxN) {
            var offset = 0
            out.add(w.substring(offset, minOf(offset + n, w.length)))
            while (offset + n < w.length) {
                offset++
                out.add(w.substring(offset, offset + n))
            }
            if (offset == 0) break
        }
    }
    return out
}

private fun softmax(scores: List<Double>): List<Double> {
    val max = scores.max()
    val exps = scores.map { exp(it - max) }
    val sum = exps.sum()
    return exps.map { it / sum }
}
