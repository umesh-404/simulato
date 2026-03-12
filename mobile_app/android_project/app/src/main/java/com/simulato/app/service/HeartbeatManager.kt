package com.simulato.app.service

import com.simulato.app.networking.ApiClient
import com.simulato.app.shared.AppLogger
import com.simulato.app.shared.Constants
import java.util.Timer
import java.util.TimerTask

class HeartbeatManager(private val apiClient: ApiClient) {

    private var timer: Timer? = null

    @Volatile
    var isRunning = false
        private set

    @Volatile
    var lastAckSuccess = false
        private set

    fun start() {
        if (isRunning) return
        isRunning = true

        timer = Timer("heartbeat", true).also {
            it.scheduleAtFixedRate(object : TimerTask() {
                override fun run() {
                    apiClient.sendHeartbeat { success, _ ->
                        lastAckSuccess = success
                        if (!success) {
                            AppLogger.w("Heartbeat", "Heartbeat ACK failed")
                        }
                    }
                }
            }, 0L, Constants.HEARTBEAT_INTERVAL_MS)
        }

        AppLogger.i("Heartbeat", "Started (interval=${Constants.HEARTBEAT_INTERVAL_MS}ms)")
    }

    fun stop() {
        timer?.cancel()
        timer = null
        isRunning = false
        AppLogger.i("Heartbeat", "Stopped")
    }
}
