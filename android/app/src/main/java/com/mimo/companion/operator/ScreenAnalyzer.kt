package com.mimo.companion.operator

import android.graphics.Bitmap
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * Screen understanding in two layers, because each one alone has a blind spot.
 *
 * The accessibility tree knows what is *actionable* — a button's real node, its enabled state, its
 * bounds — but not what a canvas drew. OCR reads what is actually *visible* — including text drawn
 * into an image, a game, or a web view that exposes nothing — but cannot tell a label from a
 * button. Combining them gives the model one honest description of the screen.
 *
 * OCR runs entirely on the device with ML Kit's bundled Latin recogniser. No screenshot leaves the
 * phone.
 */
class ScreenAnalyzer {

    private val recognizer by lazy {
        TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
    }

    suspend fun readText(bitmap: Bitmap): String = withContext(Dispatchers.Default) {
        val scaled = downscale(bitmap)
        val image = InputImage.fromBitmap(scaled, 0)
        suspendCancellableCoroutine { continuation ->
            recognizer.process(image)
                .addOnSuccessListener { result ->
                    if (continuation.isActive) continuation.resume(result.text)
                }
                .addOnFailureListener { error ->
                    if (continuation.isActive) {
                        continuation.resumeWithException(error)
                    }
                }
        }
    }

    /**
     * Full analysis: the tree is authoritative for actions, OCR fills in what the tree cannot see.
     * A capture failure is reported, not swallowed — "no screenshot permission" is a different
     * problem from "the screen is empty".
     */
    suspend fun analyse(snapshot: ScreenSnapshot): ScreenAnalysis {
        if (!ScreenCaptureService.isActive()) {
            return ScreenAnalysis(
                snapshot = snapshot,
                ocrText = "",
                captureError = "Screen capture is not enabled. Grant it in Permissions.",
                errors = snapshot.errorSignals()
            )
        }
        val bitmap = ScreenCaptureService.capture()
            ?: return ScreenAnalysis(
                snapshot = snapshot,
                ocrText = "",
                captureError = "No frame arrived from the screen.",
                errors = snapshot.errorSignals()
            )
        val text = try {
            readText(bitmap)
        } catch (e: Exception) {
            return ScreenAnalysis(
                snapshot = snapshot,
                ocrText = "",
                captureError = "Text recognition failed: ${e.message.orEmpty()}",
                errors = snapshot.errorSignals()
            )
        } finally {
            bitmap.recycle()
        }
        val enriched = snapshot.copy(ocrText = text)
        return ScreenAnalysis(
            snapshot = enriched,
            ocrText = text,
            captureError = null,
            errors = enriched.errorSignals()
        )
    }

    /** OCR is slow on a full-resolution frame and gains nothing: text stays legible at 60 %. */
    private fun downscale(bitmap: Bitmap): Bitmap {
        val maxSide = maxOf(bitmap.width, bitmap.height)
        if (maxSide <= 1400) return bitmap
        val ratio = 1400f / maxSide
        return Bitmap.createScaledBitmap(
            bitmap,
            (bitmap.width * ratio).toInt(),
            (bitmap.height * ratio).toInt(),
            true
        )
    }
}

data class ScreenAnalysis(
    val snapshot: ScreenSnapshot,
    val ocrText: String,
    val captureError: String?,
    val errors: List<String>
) {
    fun summary(): String = buildString {
        append("Package: ").append(snapshot.packageName.ifBlank { "unknown" })
        append("\nElements: ").append(snapshot.elements.size)
        val text = snapshot.allText().take(1500)
        if (text.isNotBlank()) {
            append("\nOn screen:\n").append(text)
        }
        if (errors.isNotEmpty()) {
            append("\nPossible problems:\n").append(errors.joinToString("\n"))
        }
        if (captureError != null) {
            append("\nCapture: ").append(captureError)
        }
    }
}
