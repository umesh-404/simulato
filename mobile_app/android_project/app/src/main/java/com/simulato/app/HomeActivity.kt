package com.simulato.app

import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.simulato.app.capture.CaptureActivity
import com.simulato.app.databinding.ActivityHomeBinding
import com.simulato.app.remote.RemoteControlActivity
import com.simulato.app.shared.SimulatoApp
import java.util.UUID

class HomeActivity : AppCompatActivity() {

    private lateinit var binding: ActivityHomeBinding

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityHomeBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val config = SimulatoApp.instance.config

        if (config.deviceId.isEmpty()) {
            config.deviceId = "simulato_${UUID.randomUUID().toString().take(8)}"
        }

        binding.editControllerIp.setText(config.controllerIp)
        binding.editControllerPort.setText(config.controllerPort.toString())

        binding.btnCapture.setOnClickListener {
            saveConfig()
            startActivity(Intent(this, CaptureActivity::class.java))
        }

        binding.btnRemote.setOnClickListener {
            saveConfig()
            startActivity(Intent(this, RemoteControlActivity::class.java))
        }
    }

    private fun saveConfig() {
        val config = SimulatoApp.instance.config
        val ip = binding.editControllerIp.text.toString().trim()
        val portStr = binding.editControllerPort.text.toString().trim()

        if (ip.isEmpty()) {
            Toast.makeText(this, "Controller IP is required", Toast.LENGTH_SHORT).show()
            return
        }

        config.controllerIp = ip
        config.controllerPort = portStr.toIntOrNull() ?: 8000
    }
}
