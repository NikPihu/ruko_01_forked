package com.ruko.demo

import android.content.Context

/**
 * Which simulated-world user this phone speaks for. Every request (/v1/decide, outcomes, watch,
 * episode, received) carries this id, so the server's history for it matches the phone. A demo
 * account from [com.ruko.demo.data.DemoUsers] sets it; any other sign up uses Meena.
 */
object DemoConfig {
    // Matches the demo user in sim/scenarios/meena.json.
    const val DEFAULT_USER_ID = "u_demo_meena"

    private const val PREFS = "demo_config"
    private const val KEY_USER = "user_id"

    @Volatile
    var USER_ID: String = DEFAULT_USER_ID
        private set

    /** Read the chosen user. Called from [RukoApplication], so receivers and workers see it too. */
    fun load(context: Context) {
        USER_ID = prefs(context).getString(KEY_USER, null) ?: DEFAULT_USER_ID
        com.ruko.sdk.Ruko.setUser(USER_ID)
    }

    fun select(context: Context, userId: String) {
        prefs(context).edit().putString(KEY_USER, userId).apply()
        USER_ID = userId
        com.ruko.sdk.Ruko.setUser(userId) // the RUKO SDK sends this id with every request
    }

    fun reset(context: Context) = select(context, DEFAULT_USER_ID)

    private fun prefs(context: Context) = context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
}
