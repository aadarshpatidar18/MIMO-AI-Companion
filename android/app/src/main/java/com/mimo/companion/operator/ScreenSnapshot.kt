package com.mimo.companion.operator

/**
 * A read-only picture of what is on screen: the accessibility tree flattened into elements, plus
 * whatever OCR saw. Both are the *user's own* screen, read only because they turned the service on.
 */
data class ScreenSnapshot(
    val packageName: String,
    val activity: String = "",
    val elements: List<ElementInfo> = emptyList(),
    val ocrText: String = "",
    val capturedAt: String = ""
) {
    val visibleText: String
        get() = elements.mapNotNull { it.text.takeIf { t -> t.isNotBlank() } }
            .distinct()
            .joinToString("\n")

    /** Every word on screen, tree first, OCR appended: OCR catches text drawn to a canvas. */
    fun allText(): String = buildString {
        append(visibleText)
        if (ocrText.isNotBlank()) {
            if (isNotEmpty()) append('\n')
            append(ocrText)
        }
    }

    fun find(query: String): ElementInfo? = rank(query).firstOrNull()

    fun findAll(query: String): List<ElementInfo> = rank(query)

    fun editable(): List<ElementInfo> = elements.filter { it.editable && it.enabled }

    fun clickable(): List<ElementInfo> = elements.filter { it.clickable && it.enabled }

    /**
     * Ordered best-to-worst. Scoring, not first-hit: a screen has many nodes saying "OK", and the
     * one a person means is the enabled, tappable, visible one — not the first in tree order, which
     * is often an off-screen duplicate or a disabled placeholder.
     */
    fun rank(query: String): List<ElementInfo> {
        val q = query.trim()
        if (q.isEmpty()) return emptyList()
        val lower = q.lowercase()
        return elements
            .filter { it.matches(q) }
            .map { it to score(it, lower) }
            .filter { it.second > 0 }
            .sortedWith(compareByDescending<Pair<ElementInfo, Int>> { it.second }
                .thenBy { it.first.bounds.width * it.first.bounds.height })
            .map { it.first }
    }

    private fun score(element: ElementInfo, query: String): Int {
        var score = 0
        val text = element.text.lowercase()
        val description = element.description.lowercase()
        val id = element.viewId.substringAfterLast('/').lowercase()
        when {
            text == query -> score += 100
            text.startsWith(query) -> score += 80
            text.contains(query) -> score += 60
            description == query -> score += 70
            description.contains(query) -> score += 40
            id == query -> score += 55
            id.contains(query) -> score += 30
        }
        if (element.clickable) score += 25
        if (element.editable) score += 15
        if (element.enabled) score += 10
        if (element.bounds.isEmpty) score -= 40
        // Deeper nodes are usually the concrete control rather than a container that repeats
        // its child's text.
        score += element.depth.coerceAtMost(12)
        return score
    }

    /**
     * Text that looks like the app complaining. Used to tell the user "it did not work" with the
     * screen's own words, instead of guessing from a screenshot.
     */
    fun errorSignals(): List<String> {
        val text = allText()
        if (text.isBlank()) return emptyList()
        return text.lineSequence()
            .map { it.trim() }
            .filter { line -> line.length in 3..160 && ERROR_PATTERNS.any { it.containsMatchIn(line) } }
            .distinct()
            .take(5)
            .toList()
    }

    companion object {
        private val ERROR_PATTERNS = listOf(
            Regex("(?i)\\berror\\b"),
            Regex("(?i)\\bfailed\\b"),
            Regex("(?i)\\bnot responding\\b"),
            Regex("(?i)\\binvalid\\b"),
            Regex("(?i)\\bincorrect\\b"),
            Regex("(?i)\\bwrong (password|pin|code)\\b"),
            Regex("(?i)\\b(can ?not|could ?n[o']t|unable to)\\b"),
            Regex("(?i)\\btry again\\b"),
            Regex("(?i)\\bno internet\\b"),
            Regex("(?i)\\bpermission denied\\b")
        )
    }
}
