package com.simulato.app.remote

import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.google.gson.JsonParser
import com.simulato.app.databinding.ActivityRemoteControlBinding
import com.simulato.app.networking.ApiClient
import com.simulato.app.networking.SimulatoWebSocket
import com.simulato.app.service.HeartbeatManager
import com.simulato.app.shared.AppLogger
import com.simulato.app.shared.Constants
import com.simulato.app.shared.SimulatoApp

class RemoteControlActivity : AppCompatActivity() {

    private lateinit var binding: ActivityRemoteControlBinding
    private lateinit var apiClient: ApiClient
    private lateinit var heartbeatManager: HeartbeatManager
    private lateinit var webSocket: SimulatoWebSocket

    // Auto-polling for real-time status updates.
    private val statusHandler = Handler(Looper.getMainLooper())
    private val statusPollIntervalMs = 2000L
    private var isPollingActive = false
    private var isRegistered = false
    @Volatile private var isRegistering = false

    private val statusPoller = object : Runnable {
        override fun run() {
            if (!isPollingActive || isDestroyed) return
            fetchStatus()
            statusHandler.postDelayed(this, statusPollIntervalMs)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityRemoteControlBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val config = SimulatoApp.instance.config
        apiClient = ApiClient(config)

        heartbeatManager = HeartbeatManager(apiClient) {
            runOnUiThread {
                if (isDestroyed || isRegistering) return@runOnUiThread
                isRegistered = false
                updateConnectionIndicator(false)
                registerDevice()
            }
        }

        webSocket = SimulatoWebSocket(
            config = config,
            onAlert = { alertType, message ->
                runOnUiThread {
                    if (isDestroyed) return@runOnUiThread
                    showAlert(alertType, message)
                    playAlertTone()
                }
            },
            onConnectionChange = { connected ->
                runOnUiThread {
                    if (isDestroyed) return@runOnUiThread
                    binding.txtWsStatus.text = if (connected) "WebSocket: Connected ✓" else "WebSocket: Disconnected"
                    binding.txtWsStatus.setTextColor(
                        if (connected) 0xFF4CAF50.toInt() else 0xFF616161.toInt()
                    )
                    // Trigger immediate status refresh on reconnect.
                    if (connected) fetchStatus()
                }
            },
            onRemoteCommand = null,
            onCalibrationResult = { success, message ->
                runOnUiThread {
                    if (isDestroyed) return@runOnUiThread
                    val color = if (success) 0xFF4CAF50.toInt() else 0xFFFF5252.toInt()
                    binding.txtLastAction.text = message
                    binding.txtLastAction.setTextColor(color)
                    Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
                    // Refresh status immediately after calibration.
                    fetchStatus()
                }
            }
        )

        // --- System command buttons ---
        binding.btnStart.setOnClickListener { sendCommand("START", "Starting...") }
        binding.btnPause.setOnClickListener { sendCommand("PAUSE", "Pausing...") }
        binding.btnStop.setOnClickListener { sendCommand("STOP", "Stopping...") }
        binding.btnRecalibrate.setOnClickListener { sendCommand("CALIBRATE", "Calibrating...") }
        binding.btnStatus.setOnClickListener { fetchStatus() }

        // --- Decision buttons ---
        binding.btnRequeryAi.setOnClickListener { sendDecision(Constants.OperatorDecisions.REQUERY_AI) }
        binding.btnUseDb.setOnClickListener { sendDecision(Constants.OperatorDecisions.USE_DATABASE_ANSWER) }
        binding.btnUseAi.setOnClickListener { sendDecision(Constants.OperatorDecisions.USE_AI_ANSWER) }
        binding.btnSkipQuestion.setOnClickListener { sendDecision(Constants.OperatorDecisions.SKIP_QUESTION) }

        updateConnectionIndicator(false)
        registerDevice()
    }

    // ------------------------------------------------------------------
    // Registration
    // ------------------------------------------------------------------

    private fun registerDevice() {
        if (isRegistering) return
        isRegistering = true
        binding.txtConnectionStatus.text = "● Connecting..."
        binding.txtConnectionStatus.setTextColor(0xFFFFC107.toInt())

        apiClient.register(Constants.DeviceRoles.REMOTE_CONTROL) { success, _ ->
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                isRegistering = false
                if (success) {
                    isRegistered = true
                    updateConnectionIndicator(true)
                    heartbeatManager.start()
                    webSocket.connect()
                    startStatusPolling()
                } else {
                    updateConnectionIndicator(false)
                    Toast.makeText(this, "Registration failed", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    // ------------------------------------------------------------------
    // Status polling
    // ------------------------------------------------------------------

    private fun startStatusPolling() {
        if (isPollingActive) return
        isPollingActive = true
        statusHandler.removeCallbacks(statusPoller)
        statusHandler.post(statusPoller)
    }

    private fun stopStatusPolling() {
        isPollingActive = false
        statusHandler.removeCallbacks(statusPoller)
    }

    private fun fetchStatus() {
        if (!isRegistered || isDestroyed) return

        apiClient.getStatus { success, body ->
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread

                if (!success) {
                    binding.txtLastAction.text = "Status fetch failed"
                    binding.txtLastAction.setTextColor(0xFFFF5252.toInt())
                    return@runOnUiThread
                }

                try {
                    val json = JsonParser.parseString(body).asJsonObject
                    val payload = json.getAsJsonObject("payload")

                    // System state
                    val state = payload?.get("system_state")?.asString ?: "UNKNOWN"
                    binding.txtSystemState.text = state
                    binding.txtSystemState.setTextColor(stateColor(state))

                    // Capture mode
                    val captureMode = payload?.get("capture_mode")?.asString ?: "unknown"
                    binding.txtCaptureMode.text = captureMode.uppercase()

                    // Ghost agent row (visible only in ghost mode)
                    if (captureMode == "ghost") {
                        binding.layoutGhostRow.visibility = View.VISIBLE
                        val ghostEl = payload?.get("ghost_connected")
                        if (ghostEl != null && !ghostEl.isJsonNull) {
                            val connected = ghostEl.asBoolean
                            binding.txtGhostStatus.text = if (connected) "● Connected" else "● Disconnected"
                            binding.txtGhostStatus.setTextColor(
                                if (connected) 0xFF4CAF50.toInt() else 0xFFFF5252.toInt()
                            )
                        } else {
                            binding.txtGhostStatus.text = "—"
                            binding.txtGhostStatus.setTextColor(0xFF616161.toInt())
                        }
                    } else {
                        binding.layoutGhostRow.visibility = View.GONE
                    }

                    // Question number
                    val qn = payload?.get("question_number")?.asInt ?: 0
                    binding.txtQuestionNumber.text = if (qn > 0) "#$qn" else "—"

                    // API calls
                    val apiCalls = payload?.get("api_calls")?.asInt ?: 0
                    binding.txtApiCalls.text = apiCalls.toString()

                    // Connected devices
                    val devices = payload?.get("connected_devices")?.asInt ?: 0
                    binding.txtDevices.text = devices.toString()

                    // Last action
                    val lastAction = payload?.get("last_action")?.asString ?: "—"
                    binding.txtLastAction.text = lastAction
                    binding.txtLastAction.setTextColor(0xFF78909C.toInt())

                    // Show decision panel if paused (operator needed)
                    if (state == "PAUSED" || state == "INTERVENTION") {
                        binding.layoutDecisionPanel.visibility = View.VISIBLE
                    } else {
                        binding.layoutDecisionPanel.visibility = View.GONE
                    }

                } catch (e: Exception) {
                    AppLogger.e("RemoteControl", "Status parse error", e)
                    binding.txtLastAction.text = "Parse error: ${e.message}"
                    binding.txtLastAction.setTextColor(0xFFFF5252.toInt())
                }
            }
        }
    }

    // ------------------------------------------------------------------
    // Command sending
    // ------------------------------------------------------------------

    private fun sendCommand(command: String, pendingLabel: String) {
        if (!isRegistered) {
            Toast.makeText(this, "Not connected to controller", Toast.LENGTH_SHORT).show()
            return
        }
        binding.txtLastAction.text = pendingLabel
        binding.txtLastAction.setTextColor(0xFFFFC107.toInt())

        apiClient.sendCommand(command) { success, body ->
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                if (success) {
                    binding.txtLastAction.text = "$command sent ✓"
                    binding.txtLastAction.setTextColor(0xFF4CAF50.toInt())
                } else {
                    // Try to extract error message from response.
                    val errorMsg = try {
                        val json = JsonParser.parseString(body).asJsonObject
                        val pl = json.getAsJsonObject("payload")
                        pl?.get("error")?.asString ?: body
                    } catch (_: Exception) { body }

                    binding.txtLastAction.text = "$command failed: $errorMsg"
                    binding.txtLastAction.setTextColor(0xFFFF5252.toInt())
                }
                // Refresh status 500ms after command to reflect state change.
                statusHandler.postDelayed({ fetchStatus() }, 500)
            }
        }
    }

    private fun sendDecision(decision: String) {
        binding.txtLastAction.text = "Sending decision: $decision"
        binding.txtLastAction.setTextColor(0xFFFFC107.toInt())

        apiClient.sendDecision(decision) { success, _ ->
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                if (success) {
                    binding.txtLastAction.text = "Decision sent: $decision ✓"
                    binding.txtLastAction.setTextColor(0xFF4CAF50.toInt())
                    binding.layoutDecisionPanel.visibility = View.GONE
                } else {
                    binding.txtLastAction.text = "Decision failed"
                    binding.txtLastAction.setTextColor(0xFFFF5252.toInt())
                }
                statusHandler.postDelayed({ fetchStatus() }, 500)
            }
        }
    }

    // ------------------------------------------------------------------
    // Alert handling
    // ------------------------------------------------------------------

    private fun showAlert(alertType: String, message: String) {
        binding.layoutAlertPanel.visibility = View.VISIBLE
        binding.txtAlertType.text = alertType
        binding.txtAlertMessage.text = message

        // Auto-dismiss non-critical alerts after 10 seconds.
        if (alertType != "AI_DB_CONFLICT" && alertType != "INPUT_FAILURE") {
            statusHandler.postDelayed({
                if (!isDestroyed) binding.layoutAlertPanel.visibility = View.GONE
            }, 10000)
        }
    }

    private fun playAlertTone() {
        try {
            val tone = ToneGenerator(AudioManager.STREAM_ALARM, 100)
            tone.startTone(ToneGenerator.TONE_CDMA_ALERT_CALL_GUARD, 1000)
            statusHandler.postDelayed({ tone.release() }, 1100)
        } catch (e: Exception) {
            AppLogger.e("RemoteControl", "Alert tone failed", e)
        }
    }

    // ------------------------------------------------------------------
    // UI helpers
    // ------------------------------------------------------------------

    private fun updateConnectionIndicator(connected: Boolean) {
        binding.txtConnectionStatus.text = if (connected) "● Connected" else "● Disconnected"
        binding.txtConnectionStatus.setTextColor(
            if (connected) 0xFF4CAF50.toInt() else 0xFFFF5252.toInt()
        )
    }

    private fun stateColor(state: String): Int {
        return when (state) {
            "IDLE" -> 0xFF9E9E9E.toInt()
            "CALIBRATION" -> 0xFFFFC107.toInt()
            "RUNNING" -> 0xFF4CAF50.toInt()
            "PAUSED" -> 0xFFFF9800.toInt()
            "INTERVENTION" -> 0xFFFF5252.toInt()
            "STOPPED" -> 0xFF616161.toInt()
            else -> 0xFFB0BEC5.toInt()
        }
    }

    // ------------------------------------------------------------------
    // Lifecycle
    // ------------------------------------------------------------------

    override fun onDestroy() {
        super.onDestroy()
        stopStatusPolling()
        heartbeatManager.stop()
        webSocket.disconnect()
        apiClient.shutdown()
    }
}
