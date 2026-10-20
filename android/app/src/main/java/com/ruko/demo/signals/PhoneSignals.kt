package com.ruko.demo.signals

import com.ruko.demo.net.Context as RequestContext

enum class CallKind { SIM, VOIP }

enum class CallDirection { INCOMING, OUTGOING }

/**
 * What the phone knows about calls. Null means "unknown" (no permission, or the phone does
 * not say), which Scam Shield must never read as "safe".
 */
data class CallReading(
    val active: Boolean?,
    val kind: CallKind?,
    val direction: CallDirection?,
    val callerInContacts: Boolean?,
    val startedMinAgo: Double?,
    val endedMinAgo: Double?, // a call that finished within the last 30 minutes
)

data class DeviceReading(
    val remoteAppInstalled: Boolean?,
    val remoteAppInstalledMinAgo: Double?,
    val untrustedAccessibility: Boolean?,
    val sideloadedLast24h: Boolean?,
    val screenRecorded: Boolean?, // Android 15 and later only
)

/** Everything the sensor read. [call] is null when call signals are switched off, [device] when app checks are. */
data class PhoneSignals(val call: CallReading?, val device: DeviceReading?) {

    /**
     * The `context` object of the team contract. Its fields are plain booleans, so an unknown
     * caller counts as "not in contacts" (unknown is never safe) and other unknowns as false.
     * Switching off call signals sends `context: null`, as the contract says.
     */
    fun toRequestContext(): RequestContext? {
        val c = call ?: return null
        val onCall = c.active == true
        return RequestContext(
            onCall = onCall,
            callerInContacts = if (onCall) c.callerInContacts ?: false else true,
            callMinutes = if (onCall) c.startedMinAgo?.toInt() ?: 0 else 0,
            remoteAccessApp = device?.remoteAppInstalled == true,
            accessibilityOn = device?.untrustedAccessibility == true,
            sideloadLast24h = device?.sideloadedLast24h == true,
            screenRecorded = device?.screenRecorded == true,
        )
    }
}

/**
 * Debug panel values that replace real readings. Anything set here is shown as "simulated"
 * on screen, so the demo never passes off a toggle as a real signal.
 */
data class SignalOverrides(
    val onCall: Boolean? = null,
    val callerInContacts: Boolean? = null,
    val callMinutes: Int? = null,
    val remoteApp: Boolean? = null,
    val accessibility: Boolean? = null,
    val sideload: Boolean? = null,
    val screenRecorded: Boolean? = null,
    val lureTag: String? = null,
) {
    val active: List<String>
        get() = buildList {
            if (onCall != null) add("on_call")
            if (callerInContacts != null) add("caller_in_contacts")
            if (callMinutes != null) add("call_minutes")
            if (remoteApp != null) add("remote_access_app")
            if (accessibility != null) add("accessibility_on")
            if (sideload != null) add("sideload_last_24h")
            if (screenRecorded != null) add("screen_recorded")
            if (lureTag != null) add("lure_tags")
        }

    /** Overrides only fill in groups the user consented to; a switched-off group stays null. */
    fun applyTo(real: PhoneSignals): PhoneSignals {
        val call = real.call?.let { c ->
            val active = onCall ?: c.active
            c.copy(
                active = active,
                kind = if (onCall == true) c.kind ?: CallKind.SIM else c.kind,
                callerInContacts = callerInContacts ?: c.callerInContacts,
                startedMinAgo = callMinutes?.toDouble() ?: c.startedMinAgo ?: if (onCall == true) 0.0 else null,
            )
        }
        val device = real.device?.let { d ->
            d.copy(
                remoteAppInstalled = remoteApp ?: d.remoteAppInstalled,
                untrustedAccessibility = accessibility ?: d.untrustedAccessibility,
                sideloadedLast24h = sideload ?: d.sideloadedLast24h,
                screenRecorded = screenRecorded ?: d.screenRecorded,
            )
        }
        return PhoneSignals(call, device)
    }
}
