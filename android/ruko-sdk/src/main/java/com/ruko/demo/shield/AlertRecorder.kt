package com.ruko.demo.shield

import android.content.Context
import android.util.Log
import com.ruko.demo.data.AccountStore
import com.ruko.demo.data.AlertEntry
import com.ruko.demo.data.AlertLog
import com.ruko.demo.data.AlertLogFile
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * Keeps every warning [ShieldNotifier] shows, so the Alerts screen lists it even when the
 * notification was dismissed or notifications are off. Called from the SMS receiver, the chat
 * listener and workers, so writes are serialised; a failure never stops the warning itself.
 */
object AlertRecorder {
    private val lock = Any()
    private val _version = MutableStateFlow(0)

    /** Bumped on every change, so an open Alerts screen or badge reloads. */
    val version: StateFlow<Int> = _version

    fun record(context: Context, entry: AlertEntry) {
        try {
            synchronized(lock) {
                val store = AccountStore(context.applicationContext)
                if (store.loadProfile() == null) return // no account on this phone: nothing to show it to
                store.saveAlerts(AlertLog.add(store.loadAlerts(), entry, System.currentTimeMillis()))
            }
            _version.value += 1
        } catch (e: Exception) {
            Log.w(TAG, "alert not recorded", e)
        }
    }

    fun load(context: Context): AlertLogFile = synchronized(lock) {
        val file = AccountStore(context.applicationContext).loadAlerts()
        file.copy(entries = AlertLog.trim(file.entries, System.currentTimeMillis()))
    }

    /** The user opened the Alerts screen: nothing is new any more. */
    fun markSeen(context: Context) {
        synchronized(lock) {
            val store = AccountStore(context.applicationContext)
            val file = store.loadAlerts()
            if (AlertLog.unseen(file) == 0) return
            store.saveAlerts(file.copy(seenAt = System.currentTimeMillis()))
        }
        _version.value += 1
    }

    private const val TAG = "AlertRecorder"
}
