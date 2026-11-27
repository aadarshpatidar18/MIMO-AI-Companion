package com.mimo.companion.data.remote

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import java.time.Instant

/**
 * MIMO's timestamps on the wire are **epoch seconds as a number** (SQLite REAL), not ISO strings.
 * The web interface reads them as `new Date(ts * 1000)`.
 *
 * Reading one into a Kotlin `String` fails with a decoding error, and because a single field
 * mismatch rejects the whole response, that is enough to make every screen show "MIMO sent a
 * response this app could not read". This helper accepts either shape so the app is also forward
 * compatible if the backend ever moves to ISO text.
 */
internal fun JsonElement?.toIsoInstant(): String? {
    val primitive = this as? JsonPrimitive ?: return null
    if (primitive is JsonNull) return null
    val text = primitive.content.trim()
    if (text.isEmpty()) return null
    return text.toDoubleOrNull()?.let { epochSeconds ->
        val whole = epochSeconds.toLong()
        val nanos = ((epochSeconds - whole) * 1_000_000_000L).toLong().coerceIn(0, 999_999_999)
        Instant.ofEpochSecond(whole, nanos).toString()
    } ?: text.takeIf { runCatching { Instant.parse(it) }.isSuccess }
}
