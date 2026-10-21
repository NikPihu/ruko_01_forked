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
import java.util.concurrent.TimeUnit

/** Endpoints owned by Jagdeep. Feedback (POST /v1/feedback) is added in step 8. */
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
}

object ApiClient {

    // Guide step 8: 1 s client timeout. On timeout the app proceeds and shows
    // "safety check unavailable" (fail open, never a hard block).
    private val http = OkHttpClient.Builder()
        .callTimeout(1, TimeUnit.SECONDS)
        .build()

    val api: RukoApi = retrofit(http)

    // Episode events are off the payment path: the server looks every account up, so allow longer.
    val events: RukoApi = retrofit(OkHttpClient.Builder().callTimeout(15, TimeUnit.SECONDS).build())

    private fun retrofit(client: OkHttpClient): RukoApi = Retrofit.Builder()
        .baseUrl(BuildConfig.API_BASE_URL)
        .client(client)
        .addConverterFactory(RukoJson.asConverterFactory("application/json".toMediaType()))
        .build()
        .create(RukoApi::class.java)
}
