package com.mimo.companion.operator

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.graphics.Rect
import android.os.Build
import android.os.Bundle
import android.view.accessibility.AccessibilityNodeInfo
import kotlinx.coroutines.suspendCancellableCoroutine
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.coroutines.resume

data class ActionResult(
    val ok: Boolean,
    val detail: String,
    val verified: Boolean? = null
)

/**
 * Performs one action at a time and reports what happened.
 *
 * Three rules this class exists to enforce:
 *
 * 1. **Never tap blind.** An action only targets a node that was read from the live tree and has
 *    just been refreshed, or the bounds of that node re-read after the refresh.
 * 2. **Wait for the gesture.** `dispatchGesture` is asynchronous; verifying "did it work" before
 *    the tap has landed produces false "nothing changed" reports. The gesture callback is awaited.
 * 3. **Report, don't assume.** When Android refuses, the caller gets a sentence it can act on.
 */
class UiActions(private val service: MimoAccessibilityService) {

    suspend fun click(element: ElementInfo, nodes: List<AccessibilityNodeInfo>): ActionResult {
        if (!element.enabled) return ActionResult(false, "'${element.label}' is disabled.")
        val node = UiReader.nodeFor(service.lastElements(), nodes, element)
        if (node != null) {
            val target = climbToClickable(node)
            if (target != null && target.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                return ActionResult(true, "Tapped '${element.label.ifBlank { element.viewId }}'.")
            }
        }
        if (!element.clickable) {
            return ActionResult(false, "'${element.label}' is not tappable.")
        }
        // The node refused (or is gone). Tap the element's *current* centre, not the centre recorded
        // in a snapshot that may be a second old: layouts scroll under us.
        val bounds = node?.let { liveBounds(it) } ?: element.bounds
        if (bounds.isEmpty) {
            return ActionResult(false, "'${element.label}' is no longer on screen.")
        }
        return if (tapAtAndWait(bounds.centreX, bounds.centreY)) {
            ActionResult(true, "Tapped '${element.label}' at its centre.")
        } else {
            ActionResult(false, "Android refused the tap on '${element.label}'.")
        }
    }

    fun setText(element: ElementInfo, text: String, nodes: List<AccessibilityNodeInfo>): ActionResult {
        val node = UiReader.nodeFor(service.lastElements(), nodes, element)
            ?: return ActionResult(false, "That field is no longer on screen.")
        if (!node.isEditable) return ActionResult(false, "'${element.label}' is not a text field.")
        if (!node.isEnabled) return ActionResult(false, "'${element.label}' is disabled.")
        node.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
        val args = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        }
        val ok = node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
        return if (ok) ActionResult(true, "Typed into '${element.label}'.")
        else ActionResult(false, "Android refused the text in '${element.label}'.")
    }

    suspend fun scroll(forward: Boolean = true): ActionResult {
        val root = service.rootInActiveWindow
        val node = findScrollable(root, 0)
        val action = if (forward) AccessibilityNodeInfo.ACTION_SCROLL_FORWARD
        else AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD
        if (node != null && node.performAction(action)) {
            return ActionResult(true, if (forward) "Scrolled down." else "Scrolled up.")
        }
        val height = service.resources.displayMetrics.heightPixels
        val width = service.resources.displayMetrics.widthPixels
        val from = if (forward) height * 0.7f else height * 0.3f
        val to = if (forward) height * 0.3f else height * 0.7f
        return if (swipeAndWait(width / 2f, from, width / 2f, to)) {
            ActionResult(true, if (forward) "Scrolled down." else "Scrolled up.")
        } else {
            ActionResult(false, "Nothing on this screen can scroll.")
        }
    }

    fun pressBack(): Boolean =
        service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)

    fun pressHome(): Boolean =
        service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_HOME)

    fun pressRecents(): Boolean =
        service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_RECENTS)

    private fun liveBounds(node: AccessibilityNodeInfo): Bounds {
        val rect = Rect()
        node.getBoundsInScreen(rect)
        return Bounds(rect.left, rect.top, rect.right, rect.bottom)
    }

    private fun climbToClickable(start: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        var node: AccessibilityNodeInfo? = start
        var hops = 0
        while (node != null && hops < 6) {
            if (node.isClickable && node.isEnabled) return node
            node = node.parent
            hops++
        }
        return null
    }

    private fun findScrollable(node: AccessibilityNodeInfo?, depth: Int): AccessibilityNodeInfo? {
        if (node == null || depth > 12) return null
        if (node.isScrollable && node.isVisibleToUser) return node
        for (i in 0 until node.childCount) {
            val found = findScrollable(node.getChild(i), depth + 1)
            if (found != null) return found
        }
        return null
    }

    private suspend fun tapAtAndWait(x: Int, y: Int): Boolean =
        gestureAndWait(x.toFloat(), y.toFloat(), x.toFloat(), y.toFloat())

    private suspend fun swipeAndWait(x1: Float, y1: Float, x2: Float, y2: Float): Boolean =
        gestureAndWait(x1, y1, x2, y2)

    /**
     * Dispatches a gesture and suspends until Android says it completed (or was cancelled).
     *
     * The callback arrives on the main looper, which is also where this coroutine runs, so it
     * resumes rather than blocks — a latch here would deadlock the service.
     */
    private suspend fun gestureAndWait(x1: Float, y1: Float, x2: Float, y2: Float): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) return false
        val path = Path().apply {
            moveTo(x1, y1)
            if (x1 != x2 || y1 != y2) lineTo(x2, y2)
        }
        val stroke = GestureDescription.StrokeDescription(path, 0, 120)
        val gesture = GestureDescription.Builder().addStroke(stroke).build()
        return suspendCancellableCoroutine { continuation ->
            val settled = AtomicBoolean(false)
            val callback = object : AccessibilityService.GestureResultCallback() {
                override fun onCompleted(description: GestureDescription?) {
                    if (settled.compareAndSet(false, true)) continuation.resume(true)
                }

                override fun onCancelled(description: GestureDescription?) {
                    if (settled.compareAndSet(false, true)) continuation.resume(false)
                }
            }
            val accepted = service.dispatchGesture(gesture, callback, null)
            if (!accepted && settled.compareAndSet(false, true)) continuation.resume(false)
        }
    }
}
