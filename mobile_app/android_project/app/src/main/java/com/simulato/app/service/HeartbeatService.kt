package com.simulato.app.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.IBinder
import com.simulato.app.networking.ApiClient
import com.simulato.app.shared.AppLogger
import com.simulato.app.shared.Constants
import com.simulato.app.shared.SimulatoApp

/**
 * Foreground service that keeps the heartbeat running
 * even when the app is in the background.
 *
 * Used for long exam sessions where the phone screen may turn off.
 */
class HeartbeatService : Service() {

    private var heartbeatManager: HeartbeatManager? = null
    private var apiClient: ApiClient? = null
    @Volatile
    private var isStarted = false

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (isStarted) {
            AppLogger.i("HeartbeatService", "Already running; ignoring duplicate start")
            return START_STICKY
        }

        val role = intent?.getStringExtra(EXTRA_DEVICE_ROLE) ?: Constants.DeviceRoles.REMOTE_CONTROL
        if (role != Constants.DeviceRoles.CAPTURE && role != Constants.DeviceRoles.REMOTE_CONTROL) {
            AppLogger.w("HeartbeatService", "Invalid role '$role'; defaulting to remote_control")
        }
        val effectiveRole = if (role == Constants.DeviceRoles.CAPTURE) {
            Constants.DeviceRoles.CAPTURE
        } else {
            Constants.DeviceRoles.REMOTE_CONTROL
        }

        val notification = buildNotification()
        startForeground(NOTIFICATION_ID, notification)

        val config = SimulatoApp.instance.config
        apiClient = ApiClient(config)
        heartbeatManager = HeartbeatManager(apiClient!!) {
            // Re-register automatically when controller forgets device registration.
            apiClient?.register(effectiveRole) { success, response ->
                if (success) {
                    AppLogger.i("HeartbeatService", "Re-registered successfully ($effectiveRole)")
                } else {
                    AppLogger.w("HeartbeatService", "Re-register failed: $response")
                }
            }
        }.also { it.start() }

        // Initial register is required before heartbeat ACK can succeed.
        apiClient?.register(effectiveRole) { success, response ->
            if (success) {
                AppLogger.i("HeartbeatService", "Initial register OK ($effectiveRole)")
            } else {
                AppLogger.w("HeartbeatService", "Initial register failed: $response")
            }
        }

        isStarted = true
        AppLogger.i("HeartbeatService", "Foreground service started (role=$effectiveRole)")
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        isStarted = false
        heartbeatManager?.stop()
        apiClient?.shutdown()
        AppLogger.i("HeartbeatService", "Service destroyed")
        super.onDestroy()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Simulato Heartbeat",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Keeps connection alive with controller"
            }
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(): Notification {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, CHANNEL_ID)
                .setContentTitle("Simulato")
                .setContentText("Connected to controller")
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .build()
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
                .setContentTitle("Simulato")
                .setContentText("Connected to controller")
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .build()
        }
    }

    companion object {
        const val EXTRA_DEVICE_ROLE = "extra_device_role"
        private const val CHANNEL_ID = "simulato_heartbeat"
        private const val NOTIFICATION_ID = 1001
    }
}
