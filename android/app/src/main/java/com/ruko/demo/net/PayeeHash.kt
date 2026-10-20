package com.ruko.demo.net

import com.ruko.demo.BuildConfig
import java.security.MessageDigest

/**
 * SHA-256 hex of the UPI ID plus the team salt. Must equal the Python value, or the demo
 * payee will look brand new to the server:
 *   hashlib.sha256((vpa.strip().lower() + SALT).encode()).hexdigest()
 */
fun payeeHash(vpa: String, salt: String = BuildConfig.PAYEE_SALT): String =
    MessageDigest.getInstance("SHA-256")
        .digest((vpa.trim().lowercase() + salt).toByteArray(Charsets.UTF_8))
        .joinToString("") { "%02x".format(it) }
