package com.ruko.demo.data

import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.PBEKeySpec

/** App passcode hashing. Only the salted PBKDF2 hash is stored, never the passcode. */
object Passcode {
    const val LENGTH = 6
    private const val ITERATIONS = 120_000
    private const val KEY_BITS = 256
    private val random = SecureRandom()

    fun newSalt(): String = Base64.getEncoder().encodeToString(ByteArray(16).also(random::nextBytes))

    fun hash(passcode: String, salt: String): String {
        val spec = PBEKeySpec(passcode.toCharArray(), Base64.getDecoder().decode(salt), ITERATIONS, KEY_BITS)
        return try {
            val bytes = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).encoded
            Base64.getEncoder().encodeToString(bytes)
        } finally {
            spec.clearPassword()
        }
    }

    /** Constant-time comparison so timing does not leak how close a guess was. */
    fun matches(passcode: String, salt: String, expectedHash: String): Boolean =
        MessageDigest.isEqual(hash(passcode, salt).toByteArray(), expectedHash.toByteArray())

    /** Six digit code for the demo's on-screen OTP (no SMS is sent). */
    fun newOtp(): String = (random.nextInt(900_000) + 100_000).toString()
}
