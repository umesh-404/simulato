package com.simulato.app.networking

import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.simulato.app.shared.AppConfig
import com.simulato.app.shared.AppLogger
import com.simulato.app.shared.Constants
import okhttp3.*
import java.util.concurrent.TimeUnit

class SimulatoWebSocket(
    private val config: AppConfig,
    private val onAlert: (String, String) -> Unit,
    private val onConnectionChange: (Boolean) -> Unit,
    private val onRemoteCommand: ((String) -> Unit)? = null,
    private val onCalibrationResult: ((Boolean, String) -> Unit)? = null
) {

    private val client = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()

    private var webSocket: WebSocket? = null
    private val gson = Gson()

    @Volatile
    var isConnected = false
        private set

    fun connect() {
        val request = Request.Builder()
            .url(config.wsUrl)
            .build()

        webSocket = client.newWebSocket(request, object : WebSocketListener() {

            override fun onOpen(webSocket: WebSocket, response: Response) {
                AppLogger.i("WebSocket", "Connected to ${config.wsUrl}")
                isConnected = true
                onConnectionChange(true)

                val registerMsg = JsonObject().apply {
                    addProperty("type", Constants.MessageTypes.DEVICE_REGISTER)
                    addProperty("device_id", config.deviceId)
                }
                webSocket.send(gson.toJson(registerMsg))
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                AppLogger.d("WebSocket", "Received: ${text.take(200)}")
                try {
                    val json = JsonParser.parseString(text).asJsonObject
                    val type = json.get("type")?.asString ?: return

                    when (type) {
                        Constants.MessageTypes.SYSTEM_ALERT -> {
                            val payload = json.getAsJsonObject("payload")
                            val alertType = payload?.get("alert_type")?.asString ?: "UNKNOWN"
                            val message = payload?.get("message")?.asString ?: "No details"
                            onAlert(alertType, message)
                        }
                        Constants.MessageTypes.REMOTE_COMMAND -> {
                            val payload = json.getAsJsonObject("payload")
                            val command = payload?.get("command")?.asString
                            if (command != null) {
                                AppLogger.i("WebSocket", "Remote command received: $command")
                                onRemoteCommand?.invoke(command)
                            }
                        }
                        "CALIBRATION_RESULT" -> {
                            val payload = json.getAsJsonObject("payload")
                            val success = payload?.get("success")?.asBoolean ?: false
                            val error = payload?.get("error")?.asString ?: ""
                            val msg = if (success) "Calibration successful" else "Calibration failed: $error"
                            AppLogger.i("WebSocket", msg)
                            onCalibrationResult?.invoke(success, msg)
                        }
                    }
                } catch (e: Exception) {
                    AppLogger.e("WebSocket", "Parse error: ${e.message}", e)
                }
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                AppLogger.i("WebSocket", "Closing: $code $reason")
                webSocket.close(1000, null)
                isConnected = false
                onConnectionChange(false)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                AppLogger.e("WebSocket", "Connection failed: ${t.message}", t)
                isConnected = false
                onConnectionChange(false)
            }
        })
    }

    fun disconnect() {
        webSocket?.close(1000, "User disconnect")
        isConnected = false
    }

    fun send(message: String) {
        if (isConnected) {
            webSocket?.send(message)
        } else {
            AppLogger.w("WebSocket", "Cannot send — not connected")
        }
    }
}
