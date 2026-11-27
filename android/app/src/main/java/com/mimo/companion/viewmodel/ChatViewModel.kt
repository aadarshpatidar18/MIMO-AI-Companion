package com.mimo.companion.viewmodel

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.mimo.companion.MimoApp
import com.mimo.companion.data.local.ConversationEntity
import com.mimo.companion.data.local.MessageEntity
import com.mimo.companion.data.prefs.AppSettings
import com.mimo.companion.data.remote.ApiException
import com.mimo.companion.data.repository.SendOutcome
import com.mimo.companion.device.ConnectionStatus
import com.mimo.companion.device.LinkState
import com.mimo.companion.voice.VoiceController
import com.mimo.companion.voice.VoiceState
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

@OptIn(ExperimentalCoroutinesApi::class)
class ChatViewModel(app: Application) : AndroidViewModel(app) {

    private val container = (app as MimoApp).container

    val conversations: StateFlow<List<ConversationEntity>> = container.chat.conversations
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val connection: StateFlow<ConnectionStatus> = container.connection.status

    val settings: StateFlow<AppSettings> = container.settings.settings
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), AppSettings())

    private val _active = MutableStateFlow<String?>(null)
    val active: StateFlow<String?> = _active.asStateFlow()

    val messages: StateFlow<List<MessageEntity>> = _active
        .flatMapLatest { id -> if (id == null) flowOf(emptyList()) else container.chat.messages(id) }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    var input by mutableStateOf("")
        private set

    var notice by mutableStateOf<String?>(null)
        private set

    var sending by mutableStateOf(false)
        private set

    val voice = VoiceController(app)
    val voiceState: StateFlow<VoiceState> = voice.state

    init {
        voice.initialise()
        viewModelScope.launch {
            // The repository swaps a locally-created conversation for its server id on first send;
            // follow it so the open screen does not lose its messages.
            container.chat.activeConversation.collect { id -> if (id != null) _active.value = id }
        }
        viewModelScope.launch { refresh() }
    }

    fun onInput(value: String) { input = value }

    fun dismissNotice() { notice = null }

    fun refresh() {
        viewModelScope.launch {
            runCatching { container.chat.refreshConversations() }
                .onFailure { if (it is ApiException && !it.isOffline) notice = it.message }
            val current = _active.value
            if (current != null) {
                runCatching { container.chat.syncMessages(current) }
            }
            if (_active.value == null) {
                conversations.value.firstOrNull()?.let { open(it.id) }
            }
        }
    }

    fun open(conversationId: String) {
        _active.value = conversationId
        container.chat.open(conversationId)
        viewModelScope.launch {
            runCatching { container.chat.syncMessages(conversationId) }
            runCatching { container.chat.retryQueued(conversationId) }
        }
    }

    fun newConversation() {
        viewModelScope.launch {
            runCatching {
                val id = container.chat.createConversation()
                _active.value = id
                container.chat.open(id)
                // An offline-created conversation has no server row yet; that is fine, it is pushed
                // with the first message.
            }.onFailure { notice = it.message ?: "Could not start a conversation." }
        }
    }

    fun delete(conversationId: String) {
        viewModelScope.launch {
            runCatching { container.chat.deleteConversation(conversationId) }
                .onFailure { notice = it.message ?: "Could not delete that conversation." }
            if (_active.value == conversationId) {
                _active.value = null
                conversations.value.firstOrNull()?.let { open(it.id) }
            }
        }
    }

    fun send(text: String? = null) {
        val content = (text ?: input).trim()
        if (content.isEmpty() || sending) return
        input = ""
        sending = true
        viewModelScope.launch {
            try {
                val conversationId = _active.value ?: runCatching {
                    container.chat.createConversation()
                }.getOrElse {
                    notice = it.message ?: "MIMO is not reachable."
                    return@launch
                }.also {
                    _active.value = it
                    container.chat.open(it)
                }
                when (val outcome = container.chat.send(conversationId, content)) {
                    is SendOutcome.Sent ->
                        if (settings.value.voiceReplies) voice.speak(outcome.answer)
                    SendOutcome.Queued -> notice =
                        "Queued. MIMO is offline; this sends itself when the PC is back."
                    is SendOutcome.Failed -> notice = outcome.message
                }
            } finally {
                sending = false
            }
        }
    }

    fun startVoice() {
        voice.startListening { heard -> send(heard) }
    }

    fun stopVoice() = voice.stopListening()

    fun retryQueued() {
        val id = _active.value ?: return
        viewModelScope.launch { runCatching { container.chat.retryQueued(id) } }
    }

    val isOffline: Boolean get() = connection.value.state == LinkState.OFFLINE

    override fun onCleared() {
        voice.release()
        super.onCleared()
    }
}
