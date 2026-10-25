package com.ruko.demo.signals

import com.ruko.demo.net.Handle
import java.security.MessageDigest

/**
 * Money handles in a scam message (c2-0.13): the UPI ID to pay, the link to open, the number to call
 * back. AI crews reword messages endlessly but must reuse these, so RUKO counts them across phones.
 *
 * Only the handles leave the phone, never the text (rule 2): the UPI ID plain (payees are plain,
 * rule 7), a link host or number as a salted SHA-256 pseudonym. [normalise] and [wireValue] match the
 * server's backend/graph/campaigns.py exactly; both are tested against
 * contracts/examples/handle_vectors.json. The salt is pseudonymisation, not a secret.
 */
object Handles {
    /** contracts/watch_rules.json `handle_salt` (HandlesTest checks they agree). */
    const val SALT = "ruko-handles-v1"
    const val MAX = 10

    private val VPA = Regex("^[a-z0-9][a-z0-9._-]{1,63}@[a-z]{2,20}$")
    private val HOST = Regex("^[a-z0-9-]+(\\.[a-z0-9-]+)+$")
    private val SCHEME = Regex("^[a-z][a-z0-9+.-]*://")

    // Finding candidates in a message. A UPI ID is not part of an email (no ".com" after it); a link
    // needs a scheme, "www." or a common top-level domain, so "Rs.500", "a.m." or "Mr.Sharma" are not
    // links; a number needs 10+ digits, so an OTP is not a number.
    private val FIND_VPA = Regex("(?<![a-z0-9._-])[a-z0-9][a-z0-9._-]{1,63}@[a-z]{2,20}(?![a-z0-9]|\\.[a-z0-9])", RegexOption.IGNORE_CASE)
    private val FIND_LINK = Regex(
        "(?<![@a-z0-9._-])((?:https?://)?(?:www\\.)?[a-z0-9-]+(?:\\.[a-z0-9-]+)*\\.([a-z]{2,24}))(?::\\d+)?(?:[/?#][^\\s]*)?",
        RegexOption.IGNORE_CASE,
    )
    private val COMMON_TLDS = setOf(
        "com", "in", "net", "org", "info", "co", "io", "me", "xyz", "link", "app", "site", "online", "top",
        "ly", "gl", "cc", "biz", "club", "live", "store", "shop", "click", "icu", "vip", "ink", "example", "invalid",
    )
    private val FIND_PHONE = Regex("(?<![\\d@+])(?:\\+?\\d{1,3}[\\s-]?)?\\(?\\d{2,5}\\)?(?:[\\s-]?\\d){6,10}(?![\\d@])")

    /** One canonical form per handle, or null if it is not one (same rules as the server). */
    fun normalise(kind: String, raw: String): String? {
        var s = raw.trim().lowercase()
        return when (kind) {
            "upi" -> s.takeIf { VPA.matches(it) }
            "link" -> {
                s = s.replaceFirst(SCHEME, "")
                s = s.split('/', '?', '#', limit = 2)[0]
                s = s.substringAfterLast('@').substringBefore(':').trimEnd('.')
                if (s.startsWith("www.")) s = s.removePrefix("www.")
                s.takeIf { HOST.matches(it) }
            }
            "phone" -> {
                val d = s.filter { it.isDigit() }
                when {
                    d.length == 10 && d[0] in "6789" -> "+91$d"
                    d.length == 11 && d.startsWith("0") && d[1] in "6789" -> "+91${d.substring(1)}"
                    d.length == 12 && d.startsWith("91") && d[2] in "6789" -> "+$d"
                    d.length in 8..15 -> "+$d"
                    else -> null
                }
            }
            else -> null
        }
    }

    fun hashed(kind: String, value: String, salt: String = SALT): String {
        val digest = MessageDigest.getInstance("SHA-256").digest("$salt|$kind|$value".toByteArray(Charsets.UTF_8))
        return "sha256:" + digest.joinToString("") { "%02x".format(it) }
    }

    /** What is sent for a raw handle: the UPI ID plain, link hosts and numbers hashed. */
    fun wireValue(kind: String, raw: String, salt: String = SALT): String? {
        val v = normalise(kind, raw) ?: return null
        return if (kind == "upi") v else hashed(kind, v, salt)
    }

    /** The money handles in a message, deduplicated, at most [MAX]. The text itself is never kept. */
    fun extract(body: String, salt: String = SALT): List<Handle> {
        val out = LinkedHashMap<String, Handle>()
        fun add(kind: String, raw: String) {
            val v = wireValue(kind, raw, salt) ?: return
            if (out.size < MAX) out.putIfAbsent("$kind|$v", Handle(kind, v))
        }
        FIND_VPA.findAll(body).forEach { add("upi", it.value) }
        FIND_LINK.findAll(body).forEach { m ->
            val whole = m.groupValues[1]
            val explicit = whole.contains("://") || whole.lowercase().startsWith("www.")
            if (explicit || m.groupValues[2].lowercase() in COMMON_TLDS) add("link", m.value)
        }
        FIND_PHONE.findAll(body).forEach { m -> if (m.value.count { it.isDigit() } >= 10) add("phone", m.value) }
        return out.values.toList()
    }
}
