package com.mimo.companion.operator

import android.accessibilityservice.AccessibilityService
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import kotlinx.coroutines.delay

/**
 * The operator's hands and eyes, and only that.
 *
 * It reads the active window's accessibility tree because the user turned this service on in
 * Android's own settings, and it can do exactly three things: tap an element that exists, type into
 * a field that exists, and scroll what exists. It has no overlay, no background timer, no network
 * access of its own.
 *
 * Windows are read **on demand**, not on every content-changed event. A chat list scrolling would
 * otherwise walk 400 nodes on the main thread several times a second, which is measurable jank and
 * battery drain for a picture nobody asked for.
 */
class MimoAccessibilityService : AccessibilityService() {

    companion object {
        @Volatile
        var instance: MimoAccessibilityService? = null
            private set

        fun isRunning(): Boolean = instance != null

        /** Time for the app to redraw after a tap before the result is judged. */
        const val SETTLE_MS = 220L
    }

    private val actions by lazy { UiActions(this) }

    @Volatile
    private var lastSnapshot: ScreenSnapshot? = null

    @Volatile
    private var lastNodes: List<AccessibilityNodeInfo> = emptyList()

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        OperatorBridge.attach()
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null) return
        // Only the package name is kept warm here; the tree itself is read when somebody asks.
        if (event.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
            val packageName = event.packageName?.toString().orEmpty()
            if (packageName.isNotBlank()) {
                OperatorBridge.window(packageName)
            }
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

    /**
     * Taps the best match for [label] and verifies it changed something. The verification is
     * honest: the gesture is awaited before the screen is re-read, and an unchanged screen is
     * reported as such rather than claimed as success.
     */
    suspend fun tap(label: String): ActionResult {
        val before = readScreen()
        val element = before.find(label)
            ?: return record("Tap \"$label\"", ActionResult(false, "Nothing on screen matches '$label'."))
        val result = actions.click(element, lastNodes)
        if (!result.ok) return record("Tap \"$label\"", result)
        delay(SETTLE_MS)
        val after = readScreen()
        val changed = after.packageName != before.packageName || after.allText() != before.allText()
        return record(
            "Tap \"$label\"",
            result.copy(
                verified = changed,
                detail = result.detail + if (changed) "" else " (screen looks unchanged)"
            )
        )
    }

    suspend fun typeInto(label: String, text: String): ActionResult {
        val snapshot = readScreen()
        val field = snapshot.find(label) ?: snapshot.editable().firstOrNull()
        if (field == null) {
            return record("Type into \"$label\"", ActionResult(false, "No text field on screen."))
        }
        val result = actions.setText(field, text, lastNodes)
        if (!result.ok) return record("Type into \"$label\"", result)
        delay(SETTLE_MS)
        val after = readScreen()
        val verified = after.elements.any { it.text.contains(text) }
        return record("Type into \"$label\"", result.copy(verified = verified))
    }

    suspend fun scroll(forward: Boolean = true): ActionResult {
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
