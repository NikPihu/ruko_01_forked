package com.ruko.demo.shield

import android.content.Context
import com.ruko.demo.data.Consents

/** Episode events to the server (contract c2-0.4). Filled in with the events endpoint. */
object EventSender {
    const val WORK = "shield_events"

    @Suppress("UNUSED_PARAMETER")
    fun queue(data: ShieldData, transitions: List<ShieldEngine.Transition>, consents: Consents, userId: String?, rulesVersion: String, now: Long): ShieldData = data

    @Suppress("UNUSED_PARAMETER")
    fun schedule(context: Context) = Unit
}
