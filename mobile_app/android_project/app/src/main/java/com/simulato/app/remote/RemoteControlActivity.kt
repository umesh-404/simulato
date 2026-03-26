package com.simulato.app.remote

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.widget.AdapterView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
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
    private lateinit var webSocket: SimulatoWebSocket
    private lateinit var heartbeatManager: HeartbeatManager
    private var isRegistered = false
    @Volatile private var isRegistering = false
    private var suppressSpinnerCallback = true  // Prevent initial trigger
    private var pendingCommand: String? = null
    private val statusHandler = Handler(Looper.getMainLooper())
    private val statusRunnable = object : Runnable {
        override fun run() {
            if (isDestroyed) return
            fetchStatus()
            statusHandler.postDelayed(this, 3000L)
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
                registerDevice()
            }
        }

        webSocket = SimulatoWebSocket(
            config = config,
            onAlert = { alertType, message -> onAlertReceived(alertType, message) },
            onConnectionChange = { connected -> onWsConnectionChanged(connected) },
            onRemoteCommand = null,
            onCalibrationResult = { success, message -> onCalibrationStatus(success, message) }
        )

        binding.btnStart.setOnClickListener { sendCommand(Constants.Commands.START) }
        binding.btnPause.setOnClickListener { sendCommand(Constants.Commands.PAUSE) }
        binding.btnStop.setOnClickListener { sendCommand(Constants.Commands.STOP) }
        binding.btnStatus.setOnClickListener { fetchStatus() }
        binding.btnRecalibrate.setOnClickListener { sendCommand(Constants.Commands.CALIBRATE) }

        binding.btnRequeryAi.setOnClickListener { sendDecision(Constants.OperatorDecisions.REQUERY_AI) }
        binding.btnSkipQuestion.setOnClickListener { sendDecision(Constants.OperatorDecisions.SKIP_QUESTION) }
        binding.btnUseDb.setOnClickListener { sendDecision(Constants.OperatorDecisions.USE_DATABASE_ANSWER) }
        binding.btnUseAi.setOnClickListener { sendDecision(Constants.OperatorDecisions.USE_AI_ANSWER) }

        setupAiProviderSpinner()
        registerDevice()
    }

    private fun setupAiProviderSpinner() {
        binding.spinnerAiProvider.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                if (suppressSpinnerCallback) {
                    suppressSpinnerCallback = false
                    return
                }
                val selected = parent?.getItemAtPosition(position).toString().lowercase()
                setAiProvider(selected)
            }

            override fun onNothingSelected(parent: AdapterView<*>?) {
                // Dropdown always has a selection — this won't fire
            }
        }
    }

    private fun setAiProvider(provider: String) {
        if (!isRegistered) {
            Toast.makeText(this, "Not registered", Toast.LENGTH_SHORT).show()
            return
        }
        binding.txtAiProviderStatus.text = "Switching to $provider..."
        apiClient.sendCommandWithPayload(
            Constants.Commands.SET_AI_PROVIDER,
            mapOf("provider" to provider)
        ) { success, response ->
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                binding.txtAiProviderStatus.text = if (success) {
                    "Provider: $provider"
                } else {
                    "Switch failed: $response"
                }
            }
        }
    }

    private fun registerDevice(onRegistered: (() -> Unit)? = null) {
        if (isRegistering) return
        isRegistering = true
        binding.txtConnectionStatus.text = "Connecting..."
        apiClient.register(Constants.DeviceRoles.REMOTE_CONTROL) { success, response ->
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                isRegistering = false
                if (success) {
                    isRegistered = true
                    binding.txtConnectionStatus.text = "Registered"
                    heartbeatManager.start()
                    webSocket.connect()
                    // Start live dashboard status updates
                    statusHandler.post(statusRunnable)
                    onRegistered?.invoke()
                } else {
                    isRegistered = false
                    binding.txtConnectionStatus.text = "Registration failed"
                    Toast.makeText(this, "Failed: $response", Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    private fun sendCommand(command: String) {
        if (!isRegistered) {
            pendingCommand = command
            binding.txtLastAction.text = "Re-registering..."
            registerDevice {
                pendingCommand?.let {
                    pendingCommand = null
                    sendCommandInternal(it, false)
                }
            }
            return
        }
        sendCommandInternal(command, false)
    }

    private fun sendCommandInternal(command: String, retried: Boolean) {
        binding.txtLastAction.text = "Sending: $command..."
        apiClient.sendCommand(command) { success, response ->
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                val responseError = extractCommandError(response)
                if (responseError != null && !retried && responseError.contains("not registered", ignoreCase = true)) {
                    isRegistered = false
                    registerDevice {
                        sendCommandInternal(command, true)
                    }
                    return@runOnUiThread
                }
                binding.txtLastAction.text = if (success && responseError == null) {
                    if (command == Constants.Commands.CALIBRATE) {
                        "CALIBRATE: sent, waiting for result..."
                    } else {
                        "$command: OK"
                    }
                } else {
                    if (responseError != null) "$command: FAILED ($responseError)" else "$command: FAILED"
                }
                // Reflect backend state changes immediately in UI.
                fetchStatus()
                statusHandler.removeCallbacks(statusRunnable)
                statusHandler.postDelayed(statusRunnable, 1200L)
            }
        }
    }

    private fun extractCommandError(rawResponse: String): String? {
        return try {
            val json = JsonParser.parseString(rawResponse).asJsonObject
            val payload = json.getAsJsonObject("payload")
            val status = payload?.get("status")?.asString
            if (status == "error") payload?.get("error")?.asString else null
        } catch (_: Exception) {
            null
        }
    }

    private fun sendDecision(decision: String) {
        if (!isRegistered) {
            Toast.makeText(this, "Re-registering...", Toast.LENGTH_SHORT).show()
            registerDevice { sendDecision(decision) }
            return
        }
        binding.txtLastAction.text = "Sending decision: $decision..."
        apiClient.sendDecision(decision) { success, _ ->
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                binding.txtLastAction.text = if (success) "Decision sent: $decision" else "Decision failed"
                hideDecisionPanel()
            }
        }
    }

    private fun fetchStatus() {
        binding.txtLastAction.text = "Fetching status..."
        apiClient.getStatus { success, body ->
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                if (success) {
                    val pretty = try {
                        val obj = JsonParser.parseString(body).asJsonObject
                        val payload = obj.getAsJsonObject("payload")
                        val state = payload?.get("system_state")?.asString ?: "UNKNOWN"
                        val test = payload?.get("active_test")?.asString ?: "—"
                        val provider = payload?.get("active_ai_provider")?.asString ?: "—"
                        val qn = payload?.get("question_number")?.asInt ?: 0
                        val apiCalls = payload?.get("api_calls")?.asInt ?: 0
                        val cacheHits = payload?.get("cache_hits")?.asInt ?: 0
                        val imageHashHits = payload?.get("image_hash_hits")?.asInt ?: 0
                        "state=$state\n" +
                            "test=$test\n" +
                            "provider=$provider\n" +
                            "question=$qn api_calls=$apiCalls\n" +
                            "cache_hits=$cacheHits image_hash_hits=$imageHashHits"
                    } catch (_: Exception) {
                        body
                    }
                    binding.txtSystemStatus.text = pretty
                    binding.txtLastAction.text = "Status refreshed"
                } else {
                    binding.txtSystemStatus.text = "Status unavailable: $body"
                    binding.txtLastAction.text = "Status fetch failed"
                }
            }
        }
    }

    private fun onAlertReceived(alertType: String, message: String) {
        AppLogger.w("Remote", "Alert: $alertType — $message")
        runOnUiThread {
            if (isDestroyed) return@runOnUiThread
            binding.txtAlertType.text = alertType
            binding.txtAlertMessage.text = message
            binding.layoutAlertPanel.visibility = View.VISIBLE

            if (alertType == "AI_CONFLICT" || alertType == "NO_OPTION_MATCH") {
                showDecisionPanel()
            }

            // When verification repeatedly fails, surface recalibration as the likely fix.
            if (alertType == "VERIFICATION_FAILURE") {
                binding.btnRecalibrate.visibility = View.VISIBLE
            }

            @Suppress("DEPRECATION")
            val vibrator = getSystemService(VIBRATOR_SERVICE) as? android.os.Vibrator
            vibrator?.vibrate(longArrayOf(0, 300, 100, 300), -1)

            AlertDialog.Builder(this)
                .setTitle("System Alert")
                .setMessage("$alertType\n\n$message")
                .setPositiveButton(
                    when (alertType) {
                        "CALIBRATION_REQUIRED", "CALIBRATION_FAILED" -> "Retry Calibration"
                        "CALIBRATION_COMPLETE" -> "CONTINUE"
                        else -> "OK"
                    }
                ) { _, _ ->
                    when (alertType) {
                        "CALIBRATION_REQUIRED", "CALIBRATION_FAILED" -> sendCommand(Constants.Commands.CALIBRATE)
                        "CALIBRATION_COMPLETE" -> sendCommand(Constants.Commands.CONTINUE)
                        else -> { /* noop */ }
                    }
                }
                .setCancelable(false)
                .show()
        }
    }

    private fun onCalibrationStatus(success: Boolean, message: String) {
        runOnUiThread {
            if (isDestroyed) return@runOnUiThread
            binding.txtLastAction.text = message
            Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
        }
    }

    private fun showDecisionPanel() {
        binding.layoutDecisionPanel.visibility = View.VISIBLE
    }

    private fun hideDecisionPanel() {
        binding.layoutDecisionPanel.visibility = View.GONE
        binding.layoutAlertPanel.visibility = View.GONE
    }

    private fun onWsConnectionChanged(connected: Boolean) {
        runOnUiThread {
            if (isDestroyed) return@runOnUiThread
            binding.txtWsStatus.text = if (connected) "WebSocket: Connected" else "WebSocket: Disconnected"
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        heartbeatManager.stop()
        webSocket.disconnect()
        apiClient.shutdown()
        statusHandler.removeCallbacksAndMessages(null)
    }
}
