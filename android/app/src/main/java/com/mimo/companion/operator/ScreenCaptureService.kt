package com.mimo.companion.operator

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.DisplayMetrics
import android.view.WindowManager
import androidx.core.app.NotificationCompat
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Screen capture that only runs when the user asked for a screenshot.
 *
 * Android requires a visible, ongoing notification for anything that can see the screen, and that
 * is the right trade: the user can always tell capture is armed. Frames are produced on demand by
 * [capture], never in a loop, and each frame is closed after OCR has read it.
 */
class ScreenCaptureService : Service() {

    companion object {
        const val ACTION_START = "com.mimo.companion.SCREEN_START"
        const val ACTION_STOP = "com.mimo.companion.SCREEN_STOP"
        const val EXTRA_RESULT_CODE = "result_code"
        const val EXTRA_RESULT_DATA = "result_data"
        private const val CHANNEL = "mimo_screen"
        private const val NOTIFICATION_ID = 4711

        @Volatile
        private var active: ScreenCaptureService? = null

        fun isActive(): Boolean = active != null

        /** A single frame at the current display size, or null when capture is not armed. */
        fun capture(timeoutMs: Long = 2_500): Bitmap? = active?.grab(timeoutMs)

        fun stop(context: Context) {
            context.startService(Intent(context, ScreenCaptureService::class.java).apply {
                action = ACTION_STOP
            })
        }
    }

    private var projection: MediaProjection? = null
    private var display: VirtualDisplay? = null
    private var reader: ImageReader? = null
    private val busy = AtomicBoolean(false)

    override fun onBind(intent: Intent?) = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                val code = intent.getIntExtra(EXTRA_RESULT_CODE, 0)
                val data = intent.getParcelableExtra<Intent>(EXTRA_RESULT_DATA)
                if (data == null) {
                    stopSelf()
                    return START_NOT_STICKY
                }
                startForegroundWithNotification()
                startProjection(code, data)
            }
            ACTION_STOP -> stopEverything()
        }
        return START_NOT_STICKY
    }

    private fun startProjection(code: Int, data: Intent) {
        val manager = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        val created = manager.getMediaProjection(code, data) ?: run {
            stopEverything()
            return
        }
        projection = created
        // Android 14+ requires a callback before creating the virtual display.
        created.registerCallback(object : MediaProjection.Callback() {
            override fun onStop() {
                stopEverything()
            }
        }, Handler(Looper.getMainLooper()))

        val metrics = displayMetrics()
        reader = ImageReader.newInstance(
            metrics.widthPixels, metrics.heightPixels, PixelFormat.RGBA_8888, 2
        )
        display = created.createVirtualDisplay(
            "mimo-screen",
            metrics.widthPixels, metrics.heightPixels, metrics.densityDpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            reader!!.surface, null, null
        )
        active = this
    }

    private fun displayMetrics(): DisplayMetrics {
        val wm = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        val metrics = DisplayMetrics()
        @Suppress("DEPRECATION")
        wm.defaultDisplay.getRealMetrics(metrics)
        return metrics
    }

    /** Grabs the newest available frame; returns null if none arrives inside the timeout. */
    private fun grab(timeoutMs: Long): Bitmap? {
        val imageReader = reader ?: return null
        if (!busy.compareAndSet(false, true)) return null
        try {
            val deadline = System.currentTimeMillis() + timeoutMs
            while (System.currentTimeMillis() < deadline) {
                val image = imageReader.acquireLatestImage()
                if (image != null) {
                    return try {
                        val plane = image.planes[0]
                        val rowStride = plane.rowStride
                        val pixelStride = plane.pixelStride
                        val paddedWidth = rowStride / pixelStride
                        val buffer = plane.buffer
                        val padded = Bitmap.createBitmap(
                            paddedWidth, image.height, Bitmap.Config.ARGB_8888
                        )
                        padded.copyPixelsFromBuffer(buffer)
                        if (paddedWidth != image.width) {
                            // The padded frame is a row-stride artefact, not a picture: crop it and
                            // hand back the crop, then drop the padded copy immediately. On a
                            // 1080x2400 screen that copy alone is ~10 MB.
                            val cropped = Bitmap.createBitmap(padded, 0, 0, image.width, image.height)
                            padded.recycle()
                            cropped
                        } else {
                            padded
                        }
                    } finally {
                        image.close()
                    }
                }
                Thread.sleep(60)
            }
            return null
        } catch (e: Exception) {
            return null
        } finally {
            busy.set(false)
        }
    }

    private fun startForegroundWithNotification() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL, "Screen capture", NotificationManager.IMPORTANCE_LOW)
                    .apply { description = "Shown while MIMO can take a screenshot." }
            )
        }
        val notification: Notification = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(com.mimo.companion.R.drawable.ic_launcher_foreground)
            .setContentTitle("MIMO can see the screen")
            .setContentText("Only while you ask it to read or operate this screen.")
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                NOTIFICATION_ID, notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun stopEverything() {
        active = null
        reader?.close()
        reader = null
        display?.release()
        display = null
        projection?.stop()
        projection = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        active = null
        super.onDestroy()
    }
}
