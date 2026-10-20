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
}

object ApiClient {

    // Guide step 8: 1 s client timeout. On timeout the app proceeds and shows
    // "safety check unavailable" (fail open, never a hard block).
    private val http = OkHttpClient.Builder()
        .callTimeout(1, TimeUnit.SECONDS)
        .build()

    val api: RukoApi = Retrofit.Builder()
        .baseUrl(BuildConfig.API_BASE_URL)
        .client(http)
        .addConverterFactory(RukoJson.asConverterFactory("application/json".toMediaType()))
        .build()
        .create(RukoApi::class.java)
}
