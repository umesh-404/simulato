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

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val notification = buildNotification()
        startForeground(NOTIFICATION_ID, notification)

        val config = SimulatoApp.instance.config
        apiClient = ApiClient(config)
        heartbeatManager = HeartbeatManager(apiClient!!).also { it.start() }

        AppLogger.i("HeartbeatService", "Foreground service started")
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
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
        private const val CHANNEL_ID = "simulato_heartbeat"
        private const val NOTIFICATION_ID = 1001
    }
}
