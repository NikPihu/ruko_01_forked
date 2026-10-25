package com.ruko.demo.shield

import android.content.Context
import android.util.Log
import com.ruko.demo.data.SecureStore
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import java.io.File
import java.io.IOException
import java.security.GeneralSecurityException

/** A notification already shown, so the same one is not repeated (and at most 2 a week). */
@Serializable
data class Notified(val ts: Long, val key: String)

/** Everything the background watcher keeps, encrypted in one file, for 30 days at most. */
@Serializable
data class ShieldData(
    val watcher: WatcherState = WatcherState(),
    @SerialName("last_scan_ts") val lastScanTs: Long = 0,
    val notified: List<Notified> = emptyList(),
    // Episode events waiting to be sent (c2-0.4), as encoded JSON.
    val pending: List<String> = emptyList(),
    // The server's last word on this episode ("high", "elevated"...), shown on the Alerts screen.
    @SerialName("server_risk") val serverRisk: String? = null,
    @SerialName("server_message_key") val serverMessageKey: String? = null,
)

/**
 * The money history and episode, AES-256-GCM encrypted with the same Keystore key as the
 * account (SecureStore). SMS text is never stored: only parsed amount, direction, UPI ID and time.
 * Receiver, workers and the app all go through [update], one at a time.
 */
class EpisodeStore(context: Context) {

    private val store = SecureStore(File(context.noBackupFilesDir, "secure"))

    fun load(): ShieldData = synchronized(LOCK) { read() }

    /** Read, change and write back under one lock. */
    fun update(change: (ShieldData) -> ShieldData): ShieldData = synchronized(LOCK) {
        val next = change(read())
        store.write(FILE, json.encodeToString(ShieldData.serializer(), next).encodeToByteArray())
        next
    }

    fun delete() = synchronized(LOCK) { store.delete(FILE) }

    private fun read(): ShieldData = try {
        store.read(FILE)?.let { json.decodeFromString(ShieldData.serializer(), it.decodeToString()) } ?: ShieldData()
    } catch (e: GeneralSecurityException) {
        Log.w(TAG, "could not decrypt $FILE", e)
        ShieldData()
    } catch (e: IOException) {
        Log.w(TAG, "could not read $FILE", e)
        ShieldData()
    } catch (e: SerializationException) {
        Log.w(TAG, "could not parse $FILE", e)
        ShieldData()
    }

    companion object {
        private const val TAG = "EpisodeStore"
        private const val FILE = "episode.enc"
        private val LOCK = Any()
        private val json = Json { ignoreUnknownKeys = true }

        private var cachedRules: EpisodeRules? = null

        /** contracts/episode_rules.json, copied into assets (EpisodeTrackerTest checks the copy). */
        fun rules(context: Context): EpisodeRules = cachedRules ?: context.assets.open("episode_rules.json")
            .bufferedReader().use { json.decodeFromString(EpisodeRules.serializer(), it.readText()) }
            .also { cachedRules = it }
    }
}
