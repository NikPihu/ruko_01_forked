package com.ruko.demo.data

import android.content.Context
import android.util.Log
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json

/** A ready-made account from the simulated world (`python -m sim.demo_users --write`). */
@Serializable
data class DemoUser(
    @SerialName("user_id") val userId: String,
    @SerialName("full_name") val fullName: String,
    val mobile: String,
    val email: String,
    @SerialName("date_of_birth") val dateOfBirth: String, // yyyy-MM-dd
    val language: String,
    val region: String,
    @SerialName("bank_name") val bankName: String,
    @SerialName("account_last4") val accountLast4: String,
    val ifsc: String,
    @SerialName("upi_id") val upiId: String,
)

object DemoUsers {
    const val ASSET = "demo_users.json"
    private const val TAG = "DemoUsers"
    private val json = Json { ignoreUnknownKeys = true }

    fun parse(text: String): List<DemoUser> = json.decodeFromString(ListSerializer(DemoUser.serializer()), text)

    /** The demo accounts shipped with the app; empty if the asset is missing or broken. */
    fun load(context: Context): List<DemoUser> = try {
        parse(context.assets.open(ASSET).bufferedReader().use { it.readText() })
    } catch (e: Exception) {
        Log.w(TAG, "no demo users", e)
        emptyList()
    }
}
