package com.mimo.companion.operator

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The matching rules are the part of the operator that decides *what* gets tapped. They are pure
 * Kotlin precisely so they can be tested here, on a JVM, without a phone.
 */
class ScreenSnapshotTest {

    private fun element(
        index: Int,
        text: String = "",
        description: String = "",
        viewId: String = "",
        clickable: Boolean = true,
        enabled: Boolean = true,
        editable: Boolean = false,
        bounds: Bounds = Bounds(0, 0, 200, 80),
        depth: Int = 6
    ) = ElementInfo(
        index = index, text = text, description = description, viewId = viewId,
        clickable = clickable, enabled = enabled, editable = editable,
        bounds = bounds, depth = depth
    )

    private fun screen(vararg elements: ElementInfo) = ScreenSnapshot(
        packageName = "com.example.app", elements = elements.toList()
    )

    @Test
    fun `an exact enabled button beats a container that merely contains the word`() {
        val snapshot = screen(
            element(0, text = "Search results for cats", clickable = false, depth = 2),
            element(1, text = "Search", clickable = true, depth = 9)
        )
        assertEquals("Search", snapshot.find("Search")?.text)
    }

    @Test
    fun `a disabled match loses to an enabled one`() {
        val snapshot = screen(
            element(0, text = "Send", enabled = false, depth = 8),
            element(1, text = "Send", enabled = true, depth = 8)
        )
        assertEquals(true, snapshot.find("Send")?.enabled)
    }

    @Test
    fun `accessibility label is matched when the element has no text`() {
        val snapshot = screen(element(0, description = "Compose message"))
        assertEquals(0, snapshot.find("compose")?.index)
    }

    @Test
    fun `view id tail is matched, not the whole package path`() {
        val snapshot = screen(element(0, viewId = "com.example.app:id/btn_submit"))
        assertEquals(0, snapshot.find("btn_submit")?.index)
    }

    @Test
    fun `an off screen element with empty bounds is penalised`() {
        val snapshot = screen(
            element(0, text = "Continue", bounds = Bounds(0, 0, 0, 0), depth = 8),
            element(1, text = "Continue", bounds = Bounds(20, 1400, 1000, 1500), depth = 5)
        )
        assertEquals(1, snapshot.find("Continue")?.index)
    }

    @Test
    fun `nothing matches an empty query`() {
        val snapshot = screen(element(0, text = "OK"))
        assertNull(snapshot.find("   "))
        assertTrue(snapshot.rank("").isEmpty())
    }

    @Test
    fun `an absent label returns null rather than the nearest element`() {
        val snapshot = screen(element(0, text = "Settings"), element(1, text = "Profile"))
        assertNull(snapshot.find("Delete account"))
    }

    @Test
    fun `error lines are reported with the screen's own words`() {
        val snapshot = ScreenSnapshot(
            packageName = "com.example",
            elements = listOf(
                element(0, text = "Invalid password. Please try again."),
                element(1, text = "Sign in")
            )
        )
        val errors = snapshot.errorSignals()
        assertTrue(errors.any { it.contains("Invalid password") })
        assertTrue(errors.none { it == "Sign in" })
    }

    @Test
    fun `visible text is deduplicated and keeps blanks out`() {
        val snapshot = screen(
            element(0, text = "Inbox"),
            element(1, text = "Inbox"),
            element(2, text = "")
        )
        assertEquals("Inbox", snapshot.visibleText)
    }

    @Test
    fun `bounds centre and containment are exact`() {
        val bounds = Bounds(100, 200, 300, 260)
        assertEquals(200, bounds.centreX)
        assertEquals(230, bounds.centreY)
        assertTrue(bounds.contains(200, 230))
        assertTrue(!bounds.contains(99, 230))
    }

    @Test
    fun `OCR text is appended after the tree text`() {
        val snapshot = screen(element(0, text = "Hello")).copy(ocrText = "drawn on a canvas")
        val all = snapshot.allText()
        assertTrue(all.indexOf("Hello") < all.indexOf("drawn on a canvas"))
    }

    @Test
    fun `an element that is neither labelled nor actionable still matches by id`() {
        val snapshot = screen(element(0, viewId = "android:id/title", clickable = false))
        assertTrue(snapshot.find("title") != null)
    }
}
