package com.ruko.demo.net

import java.time.OffsetDateTime
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit

/** Builds the one request the phone sends on Pay. Never put raw text, numbers or names in it. */
object RequestBuilder {

    private val IST: ZoneOffset = ZoneOffset.ofHoursMinutes(5, 30)

    /** For example 2026-11-07T10:40:00+05:30 */
    fun nowIst(): String =
        OffsetDateTime.now(IST)
            .truncatedTo(ChronoUnit.SECONDS)
            .format(DateTimeFormatter.ISO_OFFSET_DATE_TIME)

    fun build(
        userId: String,
        upiId: String,
        amountInr: Double,
        typedManually: Boolean,
        context: Context?,
        lureTags: List<LureTag> = emptyList(),
        ts: String = nowIst(),
    ): DecideRequest = DecideRequest(
        userId = userId,
        payeeVpaHash = payeeHash(upiId),
        amountInr = amountInr,
        ts = ts,
        context = context,
        lureTags = lureTags,
        payeeTypedManually = typedManually,
    )
}
