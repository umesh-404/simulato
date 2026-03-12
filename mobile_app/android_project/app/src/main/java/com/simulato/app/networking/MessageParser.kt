package com.simulato.app.networking

import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.simulato.app.shared.AppLogger

data class SimulatoMessage(
    val type: String,
    val deviceId: String?,
    val timestamp: String?,
    val payload: JsonObject?
)

object MessageParser {

    fun parse(raw: String): SimulatoMessage? {
        return try {
            val json = JsonParser.parseString(raw).asJsonObject
            SimulatoMessage(
                type = json.get("type")?.asString ?: return null,
                deviceId = json.get("device_id")?.asString,
                timestamp = json.get("timestamp")?.asString,
                payload = json.getAsJsonObject("payload")
            )
        } catch (e: Exception) {
            AppLogger.e("MessageParser", "Failed to parse: ${e.message}")
            null
        }
    }

    fun isSuccess(responseBody: String): Boolean {
        return try {
            val json = JsonParser.parseString(responseBody).asJsonObject

            // Prefer top-level "status" if present
            val topStatus = json.get("status")?.asString
            val payloadStatus = json.getAsJsonObject("payload")?.get("status")?.asString

            val status = topStatus ?: payloadStatus
            status == "accepted" || status == "received" || status == "ok"
        } catch (e: Exception) {
            false
        }
    }
}
