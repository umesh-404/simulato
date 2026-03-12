package com.simulato.app.shared

import android.content.Context
import android.content.SharedPreferences

class AppConfig(context: Context) {

    private val prefs: SharedPreferences =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    var controllerIp: String
        get() = prefs.getString(KEY_CONTROLLER_IP, DEFAULT_IP) ?: DEFAULT_IP
        set(value) = prefs.edit().putString(KEY_CONTROLLER_IP, value).apply()

    var controllerPort: Int
        get() = prefs.getInt(KEY_CONTROLLER_PORT, DEFAULT_PORT)
        set(value) = prefs.edit().putInt(KEY_CONTROLLER_PORT, value).apply()

    var deviceId: String
        get() = prefs.getString(KEY_DEVICE_ID, "") ?: ""
        set(value) = prefs.edit().putString(KEY_DEVICE_ID, value).apply()

    val baseUrl: String
        get() = "http://$controllerIp:$controllerPort"

    val wsUrl: String
        get() = "ws://$controllerIp:$controllerPort/ws/$deviceId"

    companion object {
        private const val PREFS_NAME = "simulato_config"
        private const val KEY_CONTROLLER_IP = "controller_ip"
        private const val KEY_CONTROLLER_PORT = "controller_port"
        private const val KEY_DEVICE_ID = "device_id"
        private const val DEFAULT_IP = "192.168.1.100"
        private const val DEFAULT_PORT = 8000
    }
}
