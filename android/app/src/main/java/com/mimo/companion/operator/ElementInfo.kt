package com.mimo.companion.operator

/**
 * One element of a screen, in the app's own vocabulary rather than Android's type.
 *
 * Deliberately free of Android imports: everything that decides *what* to do with a screen is
 * testable on a plain JVM, and only the two thin layers that read the tree and perform the gesture
 * need a device. That split is what makes the operator's matching logic provable instead of
 * "worked when I tried it".
 */
data class ElementInfo(
    val index: Int,
    val text: String = "",
    val description: String = "",
    val viewId: String = "",
    val className: String = "",
    val packageName: String = "",
    val bounds: Bounds = Bounds(0, 0, 0, 0),
    val clickable: Boolean = false,
    val editable: Boolean = false,
    val scrollable: Boolean = false,
    val enabled: Boolean = true,
    val checkable: Boolean = false,
    val checked: Boolean = false,
    val depth: Int = 0
) {
    /** What a person would call this element: its text, else its accessibility label. */
    val label: String get() = text.ifBlank { description }

    val centreX: Int get() = bounds.centreX
    val centreY: Int get() = bounds.centreY

    /** Elements that cannot receive a tap should never be the target of one. */
    val actionable: Boolean get() = enabled && (clickable || editable)

    fun matches(query: String): Boolean {
        val q = query.trim()
        if (q.isEmpty()) return false
        val lower = q.lowercase()
        return text.lowercase().contains(lower) ||
            description.lowercase().contains(lower) ||
            viewId.substringAfterLast('/').lowercase().contains(lower) ||
            className.substringAfterLast('.').lowercase() == lower
    }
}

data class Bounds(val left: Int, val top: Int, val right: Int, val bottom: Int) {
    val width: Int get() = (right - left).coerceAtLeast(0)
    val height: Int get() = (bottom - top).coerceAtLeast(0)
    val centreX: Int get() = left + width / 2
    val centreY: Int get() = top + height / 2
    val isEmpty: Boolean get() = width == 0 || height == 0

    fun contains(x: Int, y: Int): Boolean = x in left until right && y in top until bottom
}
