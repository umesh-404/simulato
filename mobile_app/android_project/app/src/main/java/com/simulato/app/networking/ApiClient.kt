package com.simulato.app.networking

import com.google.gson.Gson
import com.google.gson.JsonObject
import com.simulato.app.shared.AppConfig
import com.simulato.app.shared.AppLogger
import com.simulato.app.shared.Constants
import com.simulato.app.networking.MessageParser
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.time.Instant
import java.util.concurrent.TimeUnit

class ApiClient(private val config: AppConfig) {

    private val gson = Gson()
    private val client = OkHttpClient.Builder()
        .connectTimeout(Constants.COMMAND_TIMEOUT_MS, TimeUnit.MILLISECONDS)
        .readTimeout(Constants.IMAGE_UPLOAD_TIMEOUT_MS, TimeUnit.MILLISECONDS)
        .writeTimeout(Constants.IMAGE_UPLOAD_TIMEOUT_MS, TimeUnit.MILLISECONDS)
        .build()

    private val jsonType = "application/json; charset=utf-8".toMediaType()

    fun register(deviceRole: String, callback: (Boolean, String) -> Unit) {
        val payload = JsonObject().apply {
            addProperty("type", Constants.MessageTypes.DEVICE_REGISTER)
            addProperty("device_id", config.deviceId)
            addProperty("timestamp", Instant.now().toString())
            add("payload", JsonObject().apply {
                addProperty("device_role", deviceRole)
            })
        }
        post("/api/register", payload, callback)
    }

    fun sendHeartbeat(callback: (Boolean, String) -> Unit) {
        val payload = JsonObject().apply {
            addProperty("type", Constants.MessageTypes.HEARTBEAT)
            addProperty("device_id", config.deviceId)
            addProperty("timestamp", Instant.now().toString())
        }
        post("/api/heartbeat", payload, callback)
    }

    fun sendCommand(command: String, callback: (Boolean, String) -> Unit) {
        val payload = JsonObject().apply {
            addProperty("type", Constants.MessageTypes.REMOTE_COMMAND)
            addProperty("device_id", config.deviceId)
            addProperty("timestamp", Instant.now().toString())
            add("payload", JsonObject().apply {
                addProperty("command", command)
            })
        }
        post("/api/command", payload, callback)
    }

    fun sendCommandWithPayload(command: String, extraData: Map<String, String>, callback: (Boolean, String) -> Unit) {
        val payload = JsonObject().apply {
            addProperty("type", Constants.MessageTypes.REMOTE_COMMAND)
            addProperty("device_id", config.deviceId)
            addProperty("timestamp", Instant.now().toString())
            add("payload", JsonObject().apply {
                addProperty("command", command)
                extraData.forEach { (key, value) -> addProperty(key, value) }
            })
        }
        post("/api/command", payload, callback)
    }

    fun sendDecision(decision: String, callback: (Boolean, String) -> Unit) {
        val payload = JsonObject().apply {
            addProperty("type", Constants.MessageTypes.OPERATOR_DECISION)
            addProperty("device_id", config.deviceId)
            addProperty("timestamp", Instant.now().toString())
            add("payload", JsonObject().apply {
                addProperty("decision", decision)
            })
        }
        post("/api/decision", payload, callback)
    }

    fun uploadImage(imageBytes: ByteArray, callback: (Boolean, String) -> Unit) {
        val base64 = android.util.Base64.encodeToString(imageBytes, android.util.Base64.NO_WRAP)
        val payload = JsonObject().apply {
            addProperty("device_id", config.deviceId)
            addProperty("timestamp", Instant.now().toString())
            addProperty("image", base64)
        }
        post("/api/upload_image", payload, callback)
    }

    fun getStatus(callback: (Boolean, String) -> Unit) {
        val url = "${config.baseUrl}/api/status"
        val request = Request.Builder().url(url).get().build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                AppLogger.e("ApiClient", "GET /status failed: ${e.message}")
                callback(false, e.message ?: "Connection failed")
            }

            override fun onResponse(call: Call, response: Response) {
                val body = response.body?.string() ?: ""
                callback(response.isSuccessful, body)
            }
        })
    }

    private fun post(path: String, json: JsonObject, callback: (Boolean, String) -> Unit) {
        val url = "${config.baseUrl}$path"
        val body = gson.toJson(json).toRequestBody(jsonType)
        val request = Request.Builder().url(url).post(body).build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                AppLogger.e("ApiClient", "POST $path failed: ${e.message}")
                callback(false, e.message ?: "Connection failed")
            }

            override fun onResponse(call: Call, response: Response) {
                val responseBody = response.body?.string() ?: ""
                if (response.isSuccessful) {
                    val logicalSuccess = MessageParser.isSuccess(responseBody)
                    if (logicalSuccess) {
                        AppLogger.d("ApiClient", "POST $path OK")
                        callback(true, responseBody)
                    } else {
                        AppLogger.w("ApiClient", "POST $path logical error: $responseBody")
                        callback(false, responseBody)
                    }
                } else {
                    AppLogger.w("ApiClient", "POST $path ${response.code}: $responseBody")
                    callback(false, responseBody)
                }
            }
        })
    }

    fun shutdown() {
        client.dispatcher.executorService.shutdown()
        client.connectionPool.evictAll()
    }
}
