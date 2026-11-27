package com.mimo.companion.viewmodel

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.mimo.companion.BuildConfig
import com.mimo.companion.MimoApp
import com.mimo.companion.data.prefs.AppSettings
import com.mimo.companion.data.remote.ApiException
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

class SettingsViewModel(app: Application) : AndroidViewModel(app) {

    private val container = (app as MimoApp).container

    val settings: StateFlow<AppSettings> = container.settings.settings
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), AppSettings())

    val connection = container.connection.status

    var url by mutableStateOf("")
        private set
    var code by mutableStateOf("")
        private set
    var deviceName by mutableStateOf(android.os.Build.MODEL ?: "Android phone")
        private set
    var pairing by mutableStateOf(false)
        private set
    var notice by mutableStateOf<String?>(null)
        private set
    var deviceScopes by mutableStateOf<List<String>>(emptyList())
        private set
    var version by mutableStateOf(BuildConfig.VERSION_NAME)

    init {
        viewModelScope.launch {
            val current = container.settings.current()
            url = current.backendUrl
            deviceName = current.deviceName.ifBlank { android.os.Build.MODEL ?: "Android phone" }
            if (current.isPaired) loadMe()
        }
    }

    fun onUrl(value: String) { url = value }
    fun onCode(value: String) { code = value.uppercase().take(12) }
    fun onDeviceName(value: String) { deviceName = value }
    fun dismiss() { notice = null }

    fun saveUrl() {
        viewModelScope.launch {
            runCatching { container.settings.setBackendUrl(url) }
                .onSuccess {
                    notice = "Address saved."
                    container.connection.probeOnce()
                }
                .onFailure { notice = it.message }
        }
    }

    fun pair() {
        if (code.trim().length < 4) { notice = "Enter the code shown on your MIMO PC."; return }
        pairing = true
        viewModelScope.launch {
            try {
                container.settings.setBackendUrl(url)
                val device = container.auth.pair(code, deviceName.ifBlank { "Android phone" })
                code = ""
                deviceScopes = device.scopes
                notice = "Paired as ${device.name}."
                container.connection.probeOnce()
            } catch (e: ApiException) {
                notice = e.message
            } catch (e: Exception) {
                notice = e.message ?: "Pairing failed."
            } finally {
                pairing = false
            }
        }
    }

    private suspend fun loadMe() {
        runCatching { container.auth.me() }.onSuccess { me ->
            deviceScopes = me.scopes
            if (me.name.isNotBlank()) deviceName = me.name
        }
    }

    fun unpair() {
        viewModelScope.launch {
            val current = container.settings.current()
            current.deviceId?.let { id -> runCatching { container.auth.revokeSelf(id) } }
            container.auth.forgetDevice()
            deviceScopes = emptyList()
            notice = "This phone is no longer paired."
        }
    }

    fun rotateToken() {
        viewModelScope.launch {
            runCatching { container.auth.rotate() }
                .onSuccess { notice = "New token issued; the old one is dead." }
                .onFailure { notice = it.message }
        }
    }

    fun setNotifyTasks(value: Boolean) = viewModelScope.launch { container.settings.setNotifyTasks(value) }
    fun setNotifyApprovals(value: Boolean) = viewModelScope.launch { container.settings.setNotifyApprovals(value) }
    fun setNotifyActivity(value: Boolean) = viewModelScope.launch { container.settings.setNotifyActivity(value) }
    fun setVoiceReplies(value: Boolean) = viewModelScope.launch { container.settings.setVoiceReplies(value) }
    fun setOperatorEnabled(value: Boolean) = viewModelScope.launch { container.settings.setOperatorEnabled(value) }
}
