package com.ruko.demo.ui

import android.os.SystemClock
import android.util.Log
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ruko.demo.DemoConfig
import com.ruko.demo.net.ApiClient
import com.ruko.demo.net.DecideRequest
import com.ruko.demo.net.DecideResponse
import com.ruko.demo.net.RequestBuilder
import com.ruko.demo.net.RukoApi
import com.ruko.demo.net.RukoJson
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

sealed interface Decision {
    data class Result(val response: DecideResponse, val millis: Long) : Decision

    /** The server was slow, down or answered badly. The payment proceeds (fail open). */
    data object Unavailable : Decision
}

class PaymentViewModel(private val api: RukoApi = ApiClient.api) : ViewModel() {

    var upiId by mutableStateOf("")
    var amountText by mutableStateOf("")

    // True when the UPI ID was typed, false once picking from saved payees exists.
    var typedManually by mutableStateOf(true)

    var checking by mutableStateOf(false)
        private set
    var decision by mutableStateOf<Decision?>(null)
        private set
    var serverStatus by mutableStateOf<String?>(null)
        private set

    // The exact JSON sent on the last Pay; the debug panel will show this to judges.
    var lastRequestJson by mutableStateOf("")
        private set

    val amountInr: Double?
        get() = amountText.toDoubleOrNull()?.takeIf { it > 0 }

    val canPay: Boolean
        get() = upiId.trim().contains('@') && amountInr != null && !checking

    fun checkServer() {
        viewModelScope.launch {
            serverStatus = try {
                val body = withContext(Dispatchers.IO) { api.health().string() }
                "OK: ${body.take(80)}"
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                "Not reachable: ${e.message}"
            }
        }
    }

    fun pay(onDecided: (Decision) -> Unit) {
        val amount = amountInr ?: return
        val request = RequestBuilder.build(
            userId = DemoConfig.USER_ID,
            upiId = upiId,
            amountInr = amount,
            typedManually = typedManually,
            // TODO(step 6): real signals from ContextSensor. Until then send null, which the
            // server reads as "unknown", never as "safe".
            context = null,
        )
        lastRequestJson = RukoJson.encodeToString(DecideRequest.serializer(), request)
        checking = true

        viewModelScope.launch {
            val start = SystemClock.elapsedRealtime()
            val result = try {
                Decision.Result(api.decide(request), SystemClock.elapsedRealtime() - start)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                Log.w(TAG, "decide failed, failing open", e)
                Decision.Unavailable
            }
            decision = result
            checking = false
            onDecided(result)
        }
    }

    fun reset() {
        upiId = ""
        amountText = ""
        typedManually = true
        decision = null
    }

    private companion object {
        const val TAG = "RukoPay"
    }
}
