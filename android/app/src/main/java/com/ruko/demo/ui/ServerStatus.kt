package com.ruko.demo.ui

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive

/** What "Check Scam Shield" on Home found, shown in words rather than the server's raw /health reply. */
sealed interface ServerStatus {
    data object Checking : ServerStatus

    /** The server answered "ok". `model` (e.g. "lgbm-0.2") is shown only in debug builds. */
    data class Connected(val model: String?) : ServerStatus

    /** The server answered, but not "ok". */
    data object Unhealthy : ServerStatus

    /** No answer: payments still go ahead, without a safety check (rule 3, fail open). */
    data object Unreachable : ServerStatus

    companion object {
        fun fromHealth(body: String): ServerStatus {
            val health = runCatching { Json.parseToJsonElement(body) as? JsonObject }.getOrNull()
                ?: return Unhealthy
            fun field(name: String) = health[name]?.jsonPrimitive?.contentOrNull
            return if (field("status") == "ok") Connected(field("model_version")) else Unhealthy
        }
    }
}
