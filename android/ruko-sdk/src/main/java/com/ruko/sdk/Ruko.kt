package com.ruko.sdk

import android.content.Context
import android.content.Intent
import androidx.annotation.DrawableRes
import com.ruko.demo.data.Consents
import com.ruko.demo.net.ApiClient
import com.ruko.demo.net.DecideRequest
import com.ruko.demo.net.DecideResponse
import com.ruko.demo.signals.Signals
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * How a host UPI app sets up RUKO. Everything else in the SDK reads these values instead of the
 * host's own build settings.
 *
 * [userId] is the id the RUKO server knows this user by: a stable pseudonymous id from the host,
 * never a phone number. [openApp] builds the intent a RUKO notification opens; `open` names the
 * screen to show ([Ruko.OPEN_MESSAGES]) or is null for the host's home screen. [debugSenders] lets
 * numbered SMS senders count as bank alerts (emulator demos only).
 */
data class RukoConfig(
    val apiBaseUrl: String,
    val npciBaseUrl: String,
    val userId: String,
    @param:DrawableRes val smallIcon: Int = R.drawable.ruko_ic_shield,
    val openApp: (Context, String?) -> Intent,
    val debugSenders: Boolean = false,
)

/** The answer to "may this payment go ahead?", for the host's alert screens. Never a score (rule 4). */
sealed interface RukoDecision {
    /** The server's tier (T0 to T4), reasons, words key, pause, scam type and threat level. */
    data class Checked(val response: DecideResponse) : RukoDecision

    /** RUKO could not answer in time, refused the request or said so itself: the payment goes ahead (rule 3). */
    data object Unavailable : RukoDecision
}

/** The RUKO SDK's front door. Call [init] once, in the host's `Application.onCreate`. */
object Ruko {
    const val VERSION: String = BuildConfig.SDK_VERSION

    /** Notification extra naming the screen to open: "Message check" or the host's Alerts screen. */
    const val EXTRA_OPEN = "open"
    const val OPEN_MESSAGES = "messages"
    const val OPEN_ALERTS = "alerts"

    @Volatile
    private var current: RukoConfig? = null

    /** The host package name, sent with every request so the server knows which app asked. */
    @Volatile
    var hostApp: String = "unknown"
        private set

    val config: RukoConfig
        get() = current ?: error("Call Ruko.init(context, RukoConfig(...)) in Application.onCreate first")

    /** The user the server knows; "unknown" until [init] runs (e.g. in a unit test). */
    @Volatile
    var userId: String = UNKNOWN_USER
        private set

    const val UNKNOWN_USER = "unknown"

    fun init(context: Context, config: RukoConfig) {
        current = config
        userId = config.userId
        hostApp = context.packageName
        Signals.init(context.applicationContext)
    }

    /** The host signed a different user in (e.g. a demo account). */
    fun setUser(userId: String) {
        current = current?.copy(userId = userId)
        this.userId = userId
    }

    /**
     * Check one payment: reads the phone's signals under the user's [consents], asks the server
     * and fails open on anything that goes wrong. [payeeMobile] is the number the payee was paid
     * by, if any; it is only matched against the phone's contacts, never sent.
     */
    suspend fun checkPayment(
        consents: Consents,
        request: DecideRequest,
        payeeMobile: String? = null,
    ): RukoDecision {
        val reading = runCatching {
            withContext(Dispatchers.IO) { Signals.read(consents, request.payeeUpiId, null, payeeMobile) }
        }.getOrNull()
        val full = request.copy(context = reading?.context)
        return decideOrFailOpen(full.requestId) { ApiClient.api.decide(full) }
    }

    /** The fail-open rule on its own, so it can be unit tested without a phone or a server. */
    suspend fun decideOrFailOpen(requestId: String, call: suspend () -> DecideResponse): RukoDecision = try {
        val r = call()
        if (r.failOpen || r.requestId != requestId) RukoDecision.Unavailable else RukoDecision.Checked(r)
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        RukoDecision.Unavailable // timeout, no network, HTTP 422 or any other error
    }
}
