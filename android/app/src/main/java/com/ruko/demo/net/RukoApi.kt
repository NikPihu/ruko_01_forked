package com.ruko.demo.net

import com.ruko.demo.BuildConfig
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.ResponseBody
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query
import java.util.concurrent.TimeUnit

/** Endpoints owned by the backend. */
interface RukoApi {
    @GET("health")
    suspend fun health(): ResponseBody

    @POST("v1/decide")
    suspend fun decide(@Body request: DecideRequest): DecideResponse

    /** Episode events (c2-0.4), sent in the background by shield/EventSender. */
    @POST("v1/episode")
    suspend fun episode(@Body event: EpisodeEvent): EpisodeEventResponse

    /** What happened after the check (c2-0.6), sent in the background by the payment history. */
    @POST("v1/payment/outcome")
    suspend fun paymentOutcome(@Body outcome: PaymentOutcome): PaymentOutcomeResponse

    /** Money received, read from a bank SMS (c2-0.11), only with "Share money received" on. */
    @POST("v1/payment/received")
    suspend fun moneyReceived(@Body received: MoneyReceived): MoneyReceivedResponse

    /** What the user did on an alert screen (c2-0.8), sent in the background. */
    @POST("v1/feedback")
    suspend fun feedback(@Body feedback: Feedback): FeedbackResponse

    /** An early warning before any payment (c2-0.8), only with "Early warnings" on. */
    @POST("v1/watch")
    suspend fun watch(@Body event: WatchEvent): WatchEventResponse

    /** The user's own payments as RUKO recorded them (c2-0.8): plain words, never a score. */
    @GET("v1/me/payments")
    suspend fun myPayments(@Query("user_id") userId: String): MyPayments
    /** "I know this person" (demo endpoint, unauthenticated): this user trusts this payee. */
    @POST("v1/trusted/{user_id}/{payee_upi_id}")
    suspend fun trust(@Path("user_id") userId: String, @Path("payee_upi_id") payee: String): ResponseBody
}

/** The mock NPCI, playing the part a real PSP app talks to. Not part of the RUKO contract. */
interface NpciApi {
    /** UPI number mapper: the UPI ID linked to a mobile number (+91XXXXXXXXXX), and its registered name. */
    @GET("npci/mapper/{mobile}")
    suspend fun mapper(@Path("mobile") mobile: String): MapperResponse
}

@kotlinx.serialization.Serializable
data class MapperResponse(
    val mapped: Boolean,
    val mobile: String? = null,
    @kotlinx.serialization.SerialName("upi_id") val upiId: String? = null,
    @kotlinx.serialization.SerialName("registered_name") val registeredName: String? = null,
)

object ApiClient {

    // Guide step 8: 1 s client timeout. On timeout the app proceeds and shows
    // "safety check unavailable" (fail open, never a hard block).
    private val http = OkHttpClient.Builder()
        .callTimeout(1, TimeUnit.SECONDS)
        .build()

    val api: RukoApi = retrofit(http)

    // "Check Scam Shield" and the warm-up on Home: same connection pool as payments, so the first
    // payment reuses an open connection, but a slow first connection (adb reverse, a cold server)
    // is not reported as "unreachable" after 1 s.
    val status: RukoApi = retrofit(http.newBuilder().callTimeout(5, TimeUnit.SECONDS).build())

    // Episode events are off the payment path: the server looks every account up, so allow longer.
    val events: RukoApi = retrofit(OkHttpClient.Builder().callTimeout(15, TimeUnit.SECONDS).build())

    val npci: NpciApi = Retrofit.Builder()
        .baseUrl(BuildConfig.NPCI_BASE_URL)
        .client(OkHttpClient.Builder().callTimeout(5, TimeUnit.SECONDS).build())
        .addConverterFactory(RukoJson.asConverterFactory("application/json".toMediaType()))
        .build()
        .create(NpciApi::class.java)

    private fun retrofit(client: OkHttpClient): RukoApi = Retrofit.Builder()
        .baseUrl(BuildConfig.API_BASE_URL)
        .client(client)
        .addConverterFactory(RukoJson.asConverterFactory("application/json".toMediaType()))
        .build()
        .create(RukoApi::class.java)
}
