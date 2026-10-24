package com.ruko.demo

import android.app.Application

/** Runs before any activity, receiver or worker, so all of them send the same user id. */
class RukoApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        DemoConfig.load(this)
    }
}
