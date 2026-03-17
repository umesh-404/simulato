package com.simulato.app.service

import com.simulato.app.networking.ApiClient
import com.simulato.app.shared.AppLogger
import com.simulato.app.shared.Constants
import java.util.Timer
import java.util.TimerTask

class HeartbeatManager(
    private val apiClient: ApiClient,
    private val onNotRegistered: (() -> Unit)? = null,
) {

    private var timer: Timer? = null

    @Volatile
    var isRunning = false
        private set

    @Volatile
    var lastAckSuccess = false
        private set
    private var consecutiveFailures = 0

    @Synchronized
    fun start() {
        if (isRunning) return
        isRunning = true

        timer = Timer("heartbeat", true).also {
            it.scheduleAtFixedRate(object : TimerTask() {
                override fun run() {
                    apiClient.sendHeartbeat { success, response ->
                        lastAckSuccess = success
                        if (!success) {
                            consecutiveFailures += 1
                            AppLogger.w("Heartbeat", "Heartbeat ACK failed")
                            if (response.contains("not registered", ignoreCase = true) ||
                                consecutiveFailures >= Constants.MAX_RETRIES
                            ) {
                                onNotRegistered?.invoke()
                            }
                        } else {
                            consecutiveFailures = 0
                        }
                    }
                }
            }, 0L, Constants.HEARTBEAT_INTERVAL_MS)
        }

        AppLogger.i("Heartbeat", "Started (interval=${Constants.HEARTBEAT_INTERVAL_MS}ms)")
    }

    @Synchronized
    fun stop() {
        timer?.cancel()
        timer = null
        isRunning = false
        AppLogger.i("Heartbeat", "Stopped")
    }
}
