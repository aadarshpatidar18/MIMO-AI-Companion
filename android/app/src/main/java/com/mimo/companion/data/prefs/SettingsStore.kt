package com.mimo.companion.data.prefs

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.mimoDataStore: DataStore<Preferences> by preferencesDataStore(name = "mimo_settings")

/**
 * Everything the app remembers between launches. The token lives here and nowhere else in the
 * app's storage: it is never written to the Room database, a log line, or a crash report.
 */
data class AppSettings(
    val backendUrl: String = DEFAULT_URL,
    val token: String? = null,
    val deviceId: String? = null,
    val deviceName: String = "",
    val deviceKind: String = "android",
    val notifyTasks: Boolean = true,
    val notifyApprovals: Boolean = true,
    val notifyActivity: Boolean = false,
    val voiceReplies: Boolean = true,
    val sttLanguage: String = "en-US",
    val operatorEnabled: Boolean = false,
    val lastSyncAt: String? = null
) {
    val isPaired: Boolean get() = !token.isNullOrBlank() && !deviceId.isNullOrBlank()
}

const val DEFAULT_URL = "http://192.168.0.151:8000"

class SettingsStore(private val context: Context) {

    private object Keys {
        val url = stringPreferencesKey("backend_url")
        val token = stringPreferencesKey("device_token")
        val deviceId = stringPreferencesKey("device_id")
        val deviceName = stringPreferencesKey("device_name")
        val deviceKind = stringPreferencesKey("device_kind")
        val notifyTasks = booleanPreferencesKey("notify_tasks")
        val notifyApprovals = booleanPreferencesKey("notify_approvals")
        val notifyActivity = booleanPreferencesKey("notify_activity")
        val voiceReplies = booleanPreferencesKey("voice_replies")
        val sttLanguage = stringPreferencesKey("stt_language")
        val operatorEnabled = booleanPreferencesKey("operator_enabled")
        val lastSync = stringPreferencesKey("last_sync_at")
    }

    val settings: Flow<AppSettings> = context.mimoDataStore.data.map { prefs ->
        AppSettings(
            backendUrl = prefs[Keys.url] ?: DEFAULT_URL,
            token = prefs[Keys.token],
            deviceId = prefs[Keys.deviceId],
            deviceName = prefs[Keys.deviceName] ?: "",
            deviceKind = prefs[Keys.deviceKind] ?: "android",
            notifyTasks = prefs[Keys.notifyTasks] ?: true,
            notifyApprovals = prefs[Keys.notifyApprovals] ?: true,
            notifyActivity = prefs[Keys.notifyActivity] ?: false,
            voiceReplies = prefs[Keys.voiceReplies] ?: true,
            sttLanguage = prefs[Keys.sttLanguage] ?: "en-US",
            operatorEnabled = prefs[Keys.operatorEnabled] ?: false,
            lastSyncAt = prefs[Keys.lastSync]
        )
    }

    suspend fun current(): AppSettings = settings.first()

    suspend fun setBackendUrl(url: String) = context.mimoDataStore.edit { prefs ->
        prefs[Keys.url] = url.trim().trimEnd('/')
    }

    suspend fun savePairing(token: String, deviceId: String, deviceName: String, kind: String) =
        context.mimoDataStore.edit { prefs ->
            prefs[Keys.token] = token
            prefs[Keys.deviceId] = deviceId
            prefs[Keys.deviceName] = deviceName
            prefs[Keys.deviceKind] = kind
        }

    suspend fun clearPairing() = context.mimoDataStore.edit { prefs ->
        prefs.remove(Keys.token)
        prefs.remove(Keys.deviceId)
    }

    suspend fun setNotifyTasks(value: Boolean) = context.mimoDataStore.edit { it[Keys.notifyTasks] = value }
    suspend fun setNotifyApprovals(value: Boolean) = context.mimoDataStore.edit { it[Keys.notifyApprovals] = value }
    suspend fun setNotifyActivity(value: Boolean) = context.mimoDataStore.edit { it[Keys.notifyActivity] = value }
    suspend fun setVoiceReplies(value: Boolean) = context.mimoDataStore.edit { it[Keys.voiceReplies] = value }
    suspend fun setSttLanguage(value: String) = context.mimoDataStore.edit { it[Keys.sttLanguage] = value }
    suspend fun setOperatorEnabled(value: Boolean) = context.mimoDataStore.edit { it[Keys.operatorEnabled] = value }
    suspend fun setLastSync(value: String) = context.mimoDataStore.edit { it[Keys.lastSync] = value }
}
