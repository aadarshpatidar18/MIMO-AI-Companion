package com.mimo.companion.operator

import android.accessibilityservice.AccessibilityService
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

/**
 * The operator's hands and eyes, and only that.
 *
 * It reads the active window's accessibility tree because the user turned this service on in
 * Android's own settings, and it can do exactly three things: tap an element that exists, type into
 * a field that exists, and scroll what exists. It has no overlay, no background timer, no network
 * access of its own — the app decides what to ask it, and every action is recorded in
 * [OperatorBridge] so the user can see what was done on their phone.
 */
class MimoAccessibilityService : AccessibilityService() {

    companion object {
        @Volatile
        var instance: MimoAccessibilityService? = null
            private set

        fun isRunning(): Boolean = instance != null
    }

    private val actions by lazy { UiActions(this) }

    private var lastSnapshot: ScreenSnapshot? = null
    private var lastNodes: List<AccessibilityNodeInfo> = emptyList()

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        OperatorBridge.attach()
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null) return
        when (event.eventType) {
            AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED,
            AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED -> refresh(event.packageName?.toString().orEmpty())
        }
    }

    override fun onInterrupt() = Unit

    override fun onDestroy() {
        instance = null
        OperatorBridge.detach()
        super.onDestroy()
    }

    fun lastElements(): List<ElementInfo> = lastSnapshot?.elements.orEmpty()

    fun lastNodes(): List<AccessibilityNodeInfo> = lastNodes

    /** Reads the screen as it is right now. Safe to call repeatedly; each call re-reads the tree. */
    fun readScreen(): ScreenSnapshot {
        val root = rootInActiveWindow
        val packageName = root?.packageName?.toString().orEmpty()
        val (snapshot, nodes) = UiReader.snapshot(root, packageName)
        lastSnapshot = snapshot
        lastNodes = nodes
        OperatorBridge.screenRead(snapshot)
        return snapshot
    }

    private fun refresh(packageName: String) {
        if (packageName.isBlank()) return
        readScreen()
    }

    /**
     * Taps the best match for [label] and verifies it changed something. The verification is
     * honest: if the screen looks identical afterwards, the result says so rather than claiming
     * success.
     */
    fun tap(label: String): ActionResult {
        val before = readScreen()
        val element = before.find(label)
            ?: return record("Tap \"$label\"", ActionResult(false, "Nothing on screen matches '$label'."))
        val result = actions.click(element, lastNodes)
        if (!result.ok) return record("Tap \"$label\"", result)
        val after = readScreen()
        val changed = after.packageName != before.packageName ||
            after.allText() != before.allText()
        return record(
            "Tap \"$label\"",
            result.copy(verified = changed, detail = result.detail + if (changed) "" else " (screen looks unchanged)")
        )
    }

    fun typeInto(label: String, text: String): ActionResult {
        val snapshot = readScreen()
        val field = snapshot.find(label) ?: snapshot.editable().firstOrNull()
        if (field == null) {
            return record("Type into \"$label\"", ActionResult(false, "No text field on screen."))
        }
        val result = actions.setText(field, text, lastNodes)
        if (!result.ok) return record("Type into \"$label\"", result)
        val after = readScreen()
        val verified = after.elements.any { it.text.contains(text) }
        return record("Type into \"$label\"", result.copy(verified = verified))
    }

    fun scroll(forward: Boolean = true): ActionResult {
        val result = actions.scroll(forward)
        return record(if (forward) "Scroll down" else "Scroll up", result)
    }

    fun back(): ActionResult = record("Back", ActionResult(actions.pressBack(), "Android back."))

    fun home(): ActionResult = record("Home", ActionResult(actions.pressHome(), "Android home."))

    private fun record(name: String, result: ActionResult): ActionResult {
        OperatorBridge.action(name, result)
        return result
    }
}
