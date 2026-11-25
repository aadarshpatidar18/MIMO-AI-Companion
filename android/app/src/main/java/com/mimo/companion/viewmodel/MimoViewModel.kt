package com.mimo.companion.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.mimo.companion.data.model.ChatMessage
import com.mimo.companion.data.repository.MimoRepository
import java.util.UUID
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

class MimoViewModel(
    private val repository: MimoRepository = MimoRepository()
) : ViewModel() {

    private val sessionId = UUID.randomUUID().toString()

    private val _uiState = MutableStateFlow(MimoUiState())

    val uiState: StateFlow<MimoUiState> = _uiState.asStateFlow()

    init {
        checkConnection()
    }

    fun updateInput(value: String) {
        _uiState.update {
            it.copy(input = value)
        }
    }

    fun checkConnection() {
        viewModelScope.launch {
            val connected = try {
                repository.checkConnection()
            } catch (error: Exception) {
                false
            }

            _uiState.update {
                it.copy(isConnected = connected)
            }
        }
    }

    fun sendMessage() {
        val message = _uiState.value.input.trim()

        if (message.isEmpty() || _uiState.value.isLoading) return

        _uiState.update {
            it.copy(
                messages = it.messages + ChatMessage(message, true),
                input = "",
                isLoading = true
            )
        }

        viewModelScope.launch {
            try {
                val response = repository.sendMessage(
                    message,
                    sessionId
                )

                _uiState.update {
                    it.copy(
                        messages = it.messages + ChatMessage(response, false),
                        isLoading = false,
                        isConnected = true
                    )
                }

            } catch (error: Exception) {
                _uiState.update {
                    it.copy(
                        messages = it.messages + ChatMessage(
                            "I couldn't connect to my backend. Please check whether the MIMO server is running.",
                            false
                        ),
                        isLoading = false,
                        isConnected = false
                    )
                }
            }
        }
    }
}