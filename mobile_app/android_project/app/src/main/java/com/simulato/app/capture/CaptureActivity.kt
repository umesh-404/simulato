package com.simulato.app.capture

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.view.MotionEvent
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.core.*
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
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

class CaptureActivity : AppCompatActivity() {

    private lateinit var binding: ActivityCaptureBinding
    private lateinit var apiClient: ApiClient
    private lateinit var heartbeatManager: HeartbeatManager
    private lateinit var webSocket: SimulatoWebSocket
    private lateinit var cameraExecutor: ExecutorService
    private var imageCapture: ImageCapture? = null
    private var isRegistered = false
    private var zoomLevel = 1.0f
    private var camera: Camera? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityCaptureBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val config = SimulatoApp.instance.config
        apiClient = ApiClient(config)
        heartbeatManager = HeartbeatManager(apiClient)
        cameraExecutor = Executors.newSingleThreadExecutor()

        webSocket = SimulatoWebSocket(
            config = config,
            onAlert = { _, _ -> }, // Capture doesn't handle alerts
            onConnectionChange = { connected ->
                runOnUiThread {
                    binding.txtStatus.text = if (connected) "WS Connected" else "WS Disconnected"
                }
            },
            onRemoteCommand = { command ->
                if (command == "CAPTURE_IMAGE") {
                    runOnUiThread { captureAndUpload() }
                }
            },
            onCalibrationResult = { success, message ->
                runOnUiThread {
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

        binding.btnCapture.setOnClickListener { captureAndUpload() }
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
                binding.txtStatus.text = if (success) "CALIBRATE command sent" else "Failed to send CALIBRATE"
            }
        }
    }

    private fun registerDevice() {
        apiClient.register(Constants.DeviceRoles.CAPTURE) { success, response ->
            runOnUiThread {
                if (success) {
                    isRegistered = true
                    binding.txtStatus.text = "Registered as Capture Device"
                    heartbeatManager.start()
                    webSocket.connect()
                } else {
                    binding.txtStatus.text = "Registration failed: $response"
                }
            }
        }
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

    private fun captureAndUpload() {
        val capture = imageCapture ?: return
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
                        binding.txtStatus.text = if (success) "Upload complete" else "Upload failed: $response"
                    }
                }
            }

            override fun onError(exception: ImageCaptureException) {
                AppLogger.e("Capture", "Capture failed", exception)
                runOnUiThread { binding.txtStatus.text = "Capture failed" }
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
