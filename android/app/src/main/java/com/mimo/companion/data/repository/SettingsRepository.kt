package com.mimo.companion.data.repository

import com.mimo.companion.data.prefs.AppSettings
import com.mimo.companion.data.prefs.SettingsStore
import kotlinx.coroutines.flow.Flow

/** A thin façade so view models never touch DataStore directly. */
class SettingsRepository(private val store: SettingsStore) {
    val settings: Flow<AppSettings> = store.settings

    suspend fun current(): AppSettings = store.current()

    suspend fun setBackendUrl(url: String) {
        val clean = url.trim().trimEnd('/')
        require(clean.startsWith("http://") || clean.startsWith("https://")) {
            "The address must start with http:// or https://"
        }
        val host = runCatching { java.net.URI(clean).host }.getOrNull()
        require(!host.isNullOrBlank()) { "That address has no host, for example 192.168.0.151:8000." }
        if (clean.startsWith("http://") && !isPrivateHost(host)) {
            // The device token travels in a header on every call. Over the open internet that must
            // be TLS; on the user's own network plain HTTP is what the backend serves.
            throw IllegalArgumentException(
                "Use https:// for $host — it is outside your own network, and a token must not cross the internet in the clear."
            )
        }
        store.setBackendUrl(clean)
    }

    private fun isPrivateHost(host: String): Boolean {
        val h = host.lowercase()
        if (h == "localhost" || h == "10.0.2.2" || h.endsWith(".local")) return true
        val parts = h.split('.').mapNotNull { it.toIntOrNull() }
        if (parts.size != 4) return false
        val (a, b) = parts
        return a == 127 || a == 10 || (a == 192 && b == 168) || (a == 172 && b in 16..31)
    }

    suspend fun setNotifyTasks(value: Boolean) = store.setNotifyTasks(value)
    suspend fun setNotifyApprovals(value: Boolean) = store.setNotifyApprovals(value)
    suspend fun setNotifyActivity(value: Boolean) = store.setNotifyActivity(value)
    suspend fun setVoiceReplies(value: Boolean) = store.setVoiceReplies(value)
    suspend fun setSttLanguage(value: String) = store.setSttLanguage(value)
    suspend fun setOperatorEnabled(value: Boolean) = store.setOperatorEnabled(value)
    suspend fun forget() = store.clearPairing()
}
