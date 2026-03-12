package com.simulato.app.shared

import android.app.Application

class SimulatoApp : Application() {

    lateinit var config: AppConfig
        private set

    override fun onCreate() {
        super.onCreate()
        instance = this
        config = AppConfig(this)
    }

    companion object {
        lateinit var instance: SimulatoApp
            private set
    }
}
