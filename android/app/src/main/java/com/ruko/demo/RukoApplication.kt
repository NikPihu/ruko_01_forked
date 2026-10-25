package com.ruko.demo

import android.app.Application
import android.content.Intent
import com.ruko.sdk.Ruko
import com.ruko.sdk.RukoConfig

/**
 * Runs before any activity, receiver or worker. Cache Pay is the RUKO SDK's first host app: it
 * sets the SDK up here (server address, user, what a notification opens), then picks the demo user.
 */
class RukoApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        Ruko.init(
            this,
            RukoConfig(
                apiBaseUrl = BuildConfig.API_BASE_URL,
                npciBaseUrl = BuildConfig.NPCI_BASE_URL,
                userId = DemoConfig.DEFAULT_USER_ID,
                smallIcon = R.drawable.ic_launcher_foreground,
                openApp = { context, open ->
                    Intent(context, MainActivity::class.java)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
                        .apply { open?.let { putExtra(Ruko.EXTRA_OPEN, it) } }
                },
                debugSenders = BuildConfig.DEBUG, // emulator SMS come from numbers, not bank names
            ),
        )
        DemoConfig.load(this)
    }
}
