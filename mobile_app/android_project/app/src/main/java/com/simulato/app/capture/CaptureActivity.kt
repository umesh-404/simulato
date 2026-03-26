package com.simulato.app.capture

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.media.AudioManager
import android.media.ToneGenerator
import android.view.MotionEvent
import android.widget.Toast
import android.os.Handler
import android.os.Looper
import android.util.Base64
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.core.*
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.google.gson.JsonObject
import com.simulato.app.databinding.ActivityCaptureBinding
import com.simulato.app.networking.ApiClient
import com.simulato.app.networking.SimulatoWebSocket
import com.simulato.app.service.HeartbeatManager
import com.simulato.app.shared.AppLogger
import com.simulato.app.shared.Constants
import com.simulato.app.shared.SimulatoApp
import java.io.ByteArrayOutputStream
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.time.Instant

class CaptureActivity : AppCompatActivity() {

    private lateinit var binding: ActivityCaptureBinding
    private lateinit var apiClient: ApiClient
    private lateinit var heartbeatManager: HeartbeatManager
    private lateinit var webSocket: SimulatoWebSocket
    private lateinit var cameraExecutor: ExecutorService
    private var imageCapture: ImageCapture? = null
    private var isRegistered = false
    @Volatile private var isRegistering = false
    private var zoomLevel = 1.0f
    private var camera: Camera? = null

    // MJPEG-like frame streaming (capture-only): periodically send latest frames over WS.
    private val streamIntervalMs = 1200L
    private val streamHandler = Handler(Looper.getMainLooper())
    @Volatile private var isStreamingFrames = false
    @Volatile private var isCapturingStreamFrame = false
    @Volatile private var latestStreamJpeg: ByteArray? = null
    @Volatile private var streamSeq: Long = 0
    private val streamRunnable: Runnable = object : Runnable {
        override fun run() {
            if (!isStreamingFrames) return
            attemptStreamFrame()
            streamHandler.postDelayed(this, streamIntervalMs)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityCaptureBinding.inflate(layoutInflater)
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
        cameraExecutor = Executors.newSingleThreadExecutor()

        webSocket = SimulatoWebSocket(
            config = config,
            onAlert = { alertType, message ->
                runOnUiThread {
                    if (isDestroyed) return@runOnUiThread
                    if (alertType == "TEST_COMPLETE") {
                        val tone = ToneGenerator(AudioManager.STREAM_ALARM, 100)
                        try {
                            tone.startTone(ToneGenerator.TONE_CDMA_ALERT_CALL_GUARD, 1500)
                        } finally {
                            tone.release()
                        }
                        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
                    }
                }
            },
            onConnectionChange = { connected ->
                runOnUiThread {
                    if (isDestroyed) return@runOnUiThread
                    binding.txtStatus.text = if (connected) "WS Connected" else "WS Disconnected"
                }
            },
            onRemoteCommand = { command ->
                if (command == "CAPTURE_IMAGE") {
                    runOnUiThread {
                        if (isDestroyed) return@runOnUiThread
                        captureAndUpload(forceFresh = false)
                    }
                }
            },
            onCalibrationResult = { success, message ->
                runOnUiThread {
                    if (isDestroyed) return@runOnUiThread
                    binding.txtStatus.text = message
                    Toast.makeText(this, message, Toast.LENGTH_LONG).show()
                }
            }
        )

        binding.txtStatus.text = "Connecting..."

        if (allPermissionsGranted()) {
            startCamera()
        } else {
            ActivityCompat.requestPermissions(this, REQUIRED_PERMISSIONS, REQUEST_CODE_PERMISSIONS)
        }

        binding.btnCapture.setOnClickListener { captureAndUpload(forceFresh = true) }
        binding.btnCalibrate.setOnClickListener { sendCalibrateCommand() }
        binding.btnZoomIn.setOnClickListener { adjustZoom(0.1f) }
        binding.btnZoomOut.setOnClickListener { adjustZoom(-0.1f) }

        // Tap-to-focus on preview, similar to a normal camera app.
        binding.viewFinder.setOnTouchListener { _, event ->
            if (event.action == MotionEvent.ACTION_UP) {
                val factory = binding.viewFinder.meteringPointFactory
                val point = factory.createPoint(event.x, event.y)
                val action = FocusMeteringAction.Builder(point, FocusMeteringAction.FLAG_AF)
                    .setAutoCancelDuration(3, TimeUnit.SECONDS)
                    .build()
                camera?.cameraControl?.startFocusAndMetering(action)
            }
            true
        }

        registerDevice()
    }

    private fun sendCalibrateCommand() {
        if (!isRegistered) {
            Toast.makeText(this, "Not registered with controller", Toast.LENGTH_SHORT).show()
            return
        }
        binding.txtStatus.text = "Sending CALIBRATE command..."
        apiClient.sendCommand(Constants.Commands.CALIBRATE) { success, _ ->
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                binding.txtStatus.text = if (success) "CALIBRATE command sent" else "Failed to send CALIBRATE"
            }
        }
    }

    private fun registerDevice() {
        if (isRegistering) return
        isRegistering = true
        apiClient.register(Constants.DeviceRoles.CAPTURE) { success, response ->
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                isRegistering = false
                if (success) {
                    isRegistered = true
                    binding.txtStatus.text = "Registered as Capture Device"
                    heartbeatManager.start()
                    webSocket.connect()
                    startStreamingFrames()
                } else {
                    binding.txtStatus.text = "Registration failed: $response"
                }
            }
        }
    }

    private fun startStreamingFrames() {
        if (isStreamingFrames) return
        isStreamingFrames = true
        streamHandler.removeCallbacks(streamRunnable)
        streamHandler.post(streamRunnable)
        AppLogger.i("Capture", "Started frame streaming")
    }

    private fun stopStreamingFrames() {
        isStreamingFrames = false
        streamHandler.removeCallbacks(streamRunnable)
        AppLogger.i("Capture", "Stopped frame streaming")
    }

    private fun attemptStreamFrame() {
        if (isDestroyed || !isRegistered) return
        val capture = imageCapture ?: return
        if (isCapturingStreamFrame) return

        isCapturingStreamFrame = true
        capture.takePicture(cameraExecutor, object : ImageCapture.OnImageCapturedCallback() {
            override fun onCaptureSuccess(image: ImageProxy) {
                try {
                    val buffer = image.planes[0].buffer
                    val bytes = ByteArray(buffer.remaining())
                    buffer.get(bytes)

                    val outputStream = ByteArrayOutputStream()
                    val bitmap = android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                    if (bitmap == null) return
                    bitmap.compress(android.graphics.Bitmap.CompressFormat.JPEG, 70, outputStream)
                    val jpegBytes = outputStream.toByteArray()

                    latestStreamJpeg = jpegBytes

                    // Send over WS only if controller is connected; still keep the latest cached frame.
                    if (webSocket.isConnected) {
                        val seq = streamSeq + 1
                        streamSeq = seq
                        val base64 = Base64.encodeToString(jpegBytes, Base64.NO_WRAP)
                        val payload = JsonObject().apply {
                            addProperty("seq", seq)
                            addProperty("timestamp", Instant.now().toString())
                            addProperty("image_jpeg", base64)
                        }
                        val msg = JsonObject().apply {
                            addProperty("type", "STREAM_FRAME")
                            add("payload", payload)
                        }
                        webSocket.send(msg.toString())
                    }
                } catch (e: Exception) {
                    AppLogger.e("Capture", "Streaming frame failed", e)
                } finally {
                    image.close()
                    isCapturingStreamFrame = false
                }
            }

            override fun onError(exception: ImageCaptureException) {
                try {
                    AppLogger.e("Capture", "Streaming frame capture failed", exception)
                } finally {
                    isCapturingStreamFrame = false
                }
            }
        })
    }

    private fun startCamera() {
        val cameraProviderFuture = ProcessCameraProvider.getInstance(this)
        cameraProviderFuture.addListener({
            val cameraProvider = cameraProviderFuture.get()
            val preview = Preview.Builder().build().also {
                it.setSurfaceProvider(binding.viewFinder.surfaceProvider)
            }
            imageCapture = ImageCapture.Builder()
                .setCaptureMode(ImageCapture.CAPTURE_MODE_MAXIMIZE_QUALITY)
                .build()

            val cameraSelector = CameraSelector.DEFAULT_BACK_CAMERA

            try {
                cameraProvider.unbindAll()
                camera = cameraProvider.bindToLifecycle(this, cameraSelector, preview, imageCapture)
                AppLogger.i("Capture", "Camera started")
            } catch (e: Exception) {
                AppLogger.e("Capture", "Camera bind failed", e)
            }
        }, ContextCompat.getMainExecutor(this))
    }

    private fun adjustZoom(delta: Float) {
        zoomLevel = (zoomLevel + delta).coerceIn(1.0f, 10.0f)
        camera?.cameraControl?.setZoomRatio(zoomLevel)
        binding.txtZoom.text = "Zoom: ${zoomLevel}x"
    }

    private fun captureAndUpload(forceFresh: Boolean = false) {
        val cached = latestStreamJpeg
        if (!isRegistered) {
            Toast.makeText(this, "Not registered with controller", Toast.LENGTH_SHORT).show()
            return
        }
        if (!forceFresh && cached != null && cached.isNotEmpty()) {
            binding.txtStatus.text = "Uploading (cached frame)..."

            // Quick flash on the preview to indicate a capture occurred.
            binding.viewFinder.animate().cancel()
            binding.viewFinder.alpha = 1f
            binding.viewFinder.animate()
                .alpha(0.2f)
                .setDuration(80L)
                .withEndAction {
                    binding.viewFinder.animate()
                        .alpha(1f)
                        .setDuration(80L)
                        .start()
                }
                .start()

            apiClient.uploadImage(cached) { success, response ->
                runOnUiThread {
                    if (isDestroyed) return@runOnUiThread
                    binding.txtStatus.text = if (success) "Upload complete" else "Upload failed: $response"
                }
            }
            return
        }

        val capture = imageCapture
        if (capture == null) {
            binding.txtStatus.text = "Camera not ready"
            Toast.makeText(this, "Camera is still initializing", Toast.LENGTH_SHORT).show()
            return
        }
        if (!isRegistered) {
            Toast.makeText(this, "Not registered with controller", Toast.LENGTH_SHORT).show()
            return
        }

        binding.txtStatus.text = "Capturing..."

        capture.takePicture(cameraExecutor, object : ImageCapture.OnImageCapturedCallback() {
            override fun onCaptureSuccess(image: ImageProxy) {
                val buffer = image.planes[0].buffer
                val bytes = ByteArray(buffer.remaining())
                buffer.get(bytes)

                val outputStream = ByteArrayOutputStream()
                val bitmap = android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                bitmap?.compress(android.graphics.Bitmap.CompressFormat.JPEG, 90, outputStream)
                val jpegBytes = outputStream.toByteArray()

                image.close()

                runOnUiThread {
                    if (isDestroyed) return@runOnUiThread
                    // Quick flash on the preview to indicate a capture occurred.
                    binding.viewFinder.animate().cancel()
                    binding.viewFinder.alpha = 1f
                    binding.viewFinder.animate()
                        .alpha(0.2f)
                        .setDuration(80L)
                        .withEndAction {
                            binding.viewFinder.animate()
                                .alpha(1f)
                                .setDuration(80L)
                                .start()
                        }
                        .start()

                    binding.txtStatus.text = "Uploading..."
                }

                apiClient.uploadImage(jpegBytes) { success, response ->
                    runOnUiThread {
                        if (isDestroyed) return@runOnUiThread
                        binding.txtStatus.text = if (success) "Upload complete" else "Upload failed: $response"
                    }
                }
            }

            override fun onError(exception: ImageCaptureException) {
                AppLogger.e("Capture", "Capture failed", exception)
                runOnUiThread {
                    if (isDestroyed) return@runOnUiThread
                    binding.txtStatus.text = "Capture failed"
                }
            }
        })
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQUEST_CODE_PERMISSIONS) {
            if (allPermissionsGranted()) {
                startCamera()
            } else {
                Toast.makeText(this, "Camera permission required", Toast.LENGTH_LONG).show()
                finish()
            }
        }
    }

    private fun allPermissionsGranted() = REQUIRED_PERMISSIONS.all {
        ContextCompat.checkSelfPermission(baseContext, it) == PackageManager.PERMISSION_GRANTED
    }

    override fun onDestroy() {
        super.onDestroy()
        stopStreamingFrames()
        heartbeatManager.stop()
        webSocket.disconnect()
        cameraExecutor.shutdown()
        apiClient.shutdown()
    }

    companion object {
        private const val REQUEST_CODE_PERMISSIONS = 10
        private val REQUIRED_PERMISSIONS = arrayOf(Manifest.permission.CAMERA)
    }
}
