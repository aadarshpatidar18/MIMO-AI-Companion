package com.mimo.companion

import android.Manifest
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import androidx.compose.foundation.layout.fillMaxSize
import com.mimo.companion.operator.ScreenCaptureService
import com.mimo.companion.ui.MimoApp
import com.mimo.companion.ui.theme.MIMOTheme

class MainActivity : ComponentActivity() {

    companion object {
        const val EXTRA_TASK_ID = "task_id"
    }

    private val notificationPermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    private val screenCapture =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            val data = result.data
            if (result.resultCode == RESULT_OK && data != null) {
                ContextCompat.startForegroundService(
                    this,
                    Intent(this, ScreenCaptureService::class.java).apply {
                        action = ScreenCaptureService.ACTION_START
                        putExtra(ScreenCaptureService.EXTRA_RESULT_CODE, result.resultCode)
                        putExtra(ScreenCaptureService.EXTRA_RESULT_DATA, data)
                    }
                )
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // targetSdk 35+ draws edge to edge whether the app asks or not; asking makes the insets
        // explicit so Compose's Scaffold can pad the status and navigation bars correctly.
        enableEdgeToEdge()
        askForNotificationsOnce()
        // The service needs a running media projection to hand out frames; if the user already
        // granted it this launch, they asked for it again on purpose.
        setContent {
            MIMOTheme {
                Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    MimoApp(
                        onOpenAccessibility = { openAccessibilitySettings() },
                        onRequestScreenCapture = { requestScreenCapture() },
                        onRequestNotifications = { requestNotifications() }
                    )
                }
            }
        }
    }

    private fun openAccessibilitySettings() {
        runCatching {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        }
    }

    private fun requestScreenCapture() {
        val manager = getSystemService(MediaProjectionManager::class.java)
        runCatching { screenCapture.launch(manager.createScreenCaptureIntent()) }
    }

    /**
     * Asks at most once per install, and only when the permission is actually missing.
     *
     * The previous version asked on every cold start and every rotation, which is exactly the kind
     * of prompt people learn to dismiss.
     */
    private fun askForNotificationsOnce() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        val granted = ContextCompat.checkSelfPermission(
            this, Manifest.permission.POST_NOTIFICATIONS
        ) == android.content.pm.PackageManager.PERMISSION_GRANTED
        if (granted) return
        val prefs = getSharedPreferences("mimo_onboarding", MODE_PRIVATE)
        if (prefs.getBoolean("asked_notifications", false)) return
        prefs.edit().putBoolean("asked_notifications", true).apply()
        notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    /** The Settings screen's button: ask again only if the permission is still missing. */
    private fun requestNotifications() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        val granted = ContextCompat.checkSelfPermission(
            this, Manifest.permission.POST_NOTIFICATIONS
        ) == android.content.pm.PackageManager.PERMISSION_GRANTED
        if (!granted) notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
    }
}
