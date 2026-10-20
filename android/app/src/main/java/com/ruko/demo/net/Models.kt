package com.ruko.demo.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

// Mirrors schema/events.py (owned by Jagdeep). Keys must stay snake_case exactly as the contract.
// Run Jagdeep's schema test whenever a field here changes.

@Serializable
data class Context(
    @SerialName("on_call") val onCall: Boolean = false,
    @SerialName("caller_in_contacts") val callerInContacts: Boolean = true,
    @SerialName("call_minutes") val callMinutes: Int = 0,
    @SerialName("remote_access_app") val remoteAccessApp: Boolean = false,
    @SerialName("accessibility_on") val accessibilityOn: Boolean = false,
    @SerialName("sideload_last_24h") val sideloadLast24h: Boolean = false,
    @SerialName("screen_recorded") val screenRecorded: Boolean = false,
)

@Serializable
data class LureTag(val tag: String, val conf: Double)

@Serializable
data class DecideRequest(
    @SerialName("user_id") val userId: String,
    @SerialName("payee_vpa_hash") val payeeVpaHash: String,
    @SerialName("amount_inr") val amountInr: Double,
    val ts: String, // ISO 8601 with +05:30
    val context: Context? = null, // null when the user switched off call signals
    @SerialName("lure_tags") val lureTags: List<LureTag> = emptyList(),
    @SerialName("payee_typed_manually") val payeeTypedManually: Boolean = false,
)

// The contract does not write DecideResponse out yet. These are the fields the phone needs;
// confirm the names against schema/events.py with Jagdeep before H24.
@Serializable
data class DecideResponse(
    val tier: String = "T0",
    val reasons: List<String> = emptyList(),
    @SerialName("message_key") val messageKey: String? = null,
    @SerialName("pause_minutes") val pauseMinutes: Int? = null,
    @SerialName("evidence_id") val evidenceId: String? = null,
    @SerialName("case_id") val caseId: String? = null,
)

// explicitNulls sends "context": null; ignoreUnknownKeys keeps the app working when
// Jagdeep adds an optional response field.
val RukoJson = Json {
    encodeDefaults = true
    explicitNulls = true
    ignoreUnknownKeys = true
}
