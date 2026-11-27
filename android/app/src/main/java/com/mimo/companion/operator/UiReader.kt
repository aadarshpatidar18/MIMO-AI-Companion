package com.mimo.companion.operator

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo
import java.time.Instant

/**
 * Turns Android's accessibility tree into [ElementInfo]s.
 *
 * Two hard limits, both there to protect the phone: a node budget (a browser with a long article
 * can expose thousands of nodes, and reading all of them stalls the UI) and a depth budget (deep
 * custom-drawn views can nest arbitrarily). Hitting either is recorded, not hidden — the caller is
 * told the picture may be partial.
 */
object UiReader {

    const val MAX_NODES = 400
    const val MAX_DEPTH = 24

    fun snapshot(
        root: AccessibilityNodeInfo?,
        packageName: String,
        activity: String = ""
    ): Pair<ScreenSnapshot, List<AccessibilityNodeInfo>> {
        if (root == null) {
            return ScreenSnapshot(packageName, activity, emptyList(), "", Instant.now().toString()) to
                emptyList()
        }
        val elements = ArrayList<ElementInfo>(64)
        val nodes = ArrayList<AccessibilityNodeInfo>(64)
        walk(root, 0, elements, nodes)
        return ScreenSnapshot(
            packageName = packageName,
            activity = activity,
            elements = elements,
            capturedAt = Instant.now().toString()
        ) to nodes
    }

    private fun walk(
        node: AccessibilityNodeInfo,
        depth: Int,
        out: MutableList<ElementInfo>,
        nodes: MutableList<AccessibilityNodeInfo>
    ) {
        if (out.size >= MAX_NODES || depth > MAX_DEPTH) return
        val rect = Rect()
        node.getBoundsInScreen(rect)
        val text = node.text?.toString().orEmpty().trim()
        val description = node.contentDescription?.toString().orEmpty().trim()
        val visible = node.isVisibleToUser

        // Empty, invisible containers carry nothing a person could act on. Keep nodes that have a
        // label, or that can be tapped, typed into or scrolled — everything else is noise.
        val worthKeeping = visible &&
            (text.isNotEmpty() || description.isNotEmpty() || node.isEditable ||
                (node.isClickable && node.isEnabled))

        if (worthKeeping) {
            out.add(
                ElementInfo(
                    index = out.size,
                    text = text.take(300),
                    description = description.take(300),
                    viewId = node.viewIdResourceName.orEmpty(),
                    className = node.className?.toString().orEmpty(),
                    packageName = node.packageName?.toString().orEmpty(),
                    bounds = Bounds(rect.left, rect.top, rect.right, rect.bottom),
                    clickable = node.isClickable,
                    editable = node.isEditable,
                    scrollable = node.isScrollable,
                    enabled = node.isEnabled,
                    checkable = node.isCheckable,
                    checked = node.isChecked,
                    depth = depth
                )
            )
            nodes.add(node)
        }

        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            walk(child, depth + 1, out, nodes)
            if (out.size >= MAX_NODES) return
        }
    }

    /** The node behind an element of the last snapshot, if it is still attached. */
    fun nodeFor(elements: List<ElementInfo>, nodes: List<AccessibilityNodeInfo>, element: ElementInfo):
        AccessibilityNodeInfo? {
        if (element.index !in elements.indices) return null
        if (elements[element.index].index != element.index) return null
        // `isAttachedToWindow` was removed in recent SDKs; a stale node simply refuses the action,
        // which the caller already turns into an honest failure.
        return nodes.getOrNull(element.index)
    }
}
