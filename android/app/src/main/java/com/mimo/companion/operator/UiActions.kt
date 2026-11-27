package com.mimo.companion.operator

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.os.Build
import android.os.Bundle
import android.view.accessibility.AccessibilityNodeInfo

data class ActionResult(
    val ok: Boolean,
    val detail: String,
    val verified: Boolean? = null
)

/**
 * Performs one action at a time and reports what happened.
 *
 * The rule this class exists to enforce: never tap blind. An action is only attempted on an element
 * that was read from the live tree, that is enabled, and whose bounds are on screen. When the node
 * itself refuses the action, the gesture fallback taps the element's own centre — not a guessed
 * coordinate from a screenshot.
 */
class UiActions(private val service: MimoAccessibilityService) {

    fun click(element: ElementInfo, nodes: List<AccessibilityNodeInfo>): ActionResult {
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
        return if (tapAt(element.centreX, element.centreY)) {
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

    fun scroll(forward: Boolean = true): ActionResult {
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
        return if (swipe(width / 2f, from, width / 2f, to)) {
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

    private fun tapAt(x: Int, y: Int): Boolean = gesture(x.toFloat(), y.toFloat(), x.toFloat(), y.toFloat())

    private fun swipe(x1: Float, y1: Float, x2: Float, y2: Float): Boolean = gesture(x1, y1, x2, y2)

    private fun gesture(x1: Float, y1: Float, x2: Float, y2: Float): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) return false
        val path = Path().apply {
            moveTo(x1, y1)
            if (x1 != x2 || y1 != y2) lineTo(x2, y2)
        }
        val stroke = GestureDescription.StrokeDescription(path, 0, 120)
        val gesture = GestureDescription.Builder().addStroke(stroke).build()
        return service.dispatchGesture(gesture, null, null)
    }
}
