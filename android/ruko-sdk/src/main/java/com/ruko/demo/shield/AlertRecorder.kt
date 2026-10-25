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

    /**
     * Adds the warning to the Alerts list. True when it is a new alert, so the caller notifies; false
     * for a repeat of the same warning within [AlertLog.REPEAT_MS], or when there is no account here.
     * If the list cannot be written the warning is still shown (true).
     */
    fun record(context: Context, entry: AlertEntry): Boolean {
        val added = try {
            synchronized(lock) {
                val store = AccountStore(context.applicationContext)
                if (store.loadProfile() == null) return false // no account on this phone: nothing to show it to
                val file = store.loadAlerts()
                if (AlertLog.isRepeat(file, entry)) return false
                store.saveAlerts(AlertLog.add(file, entry, System.currentTimeMillis()))
                true
            }
        } catch (e: Exception) {
            Log.w(TAG, "alert not recorded", e)
            true
        }
        _version.value += 1
        return added
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
