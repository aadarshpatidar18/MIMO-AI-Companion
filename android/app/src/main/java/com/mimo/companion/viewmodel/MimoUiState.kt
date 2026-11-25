package com.mimo.companion.viewmodel

import com.mimo.companion.data.model.ChatMessage

data class MimoUiState(
    val messages: List<ChatMessage> = listOf(
        ChatMessage(
            "Hello! I'm MIMO, your personal AI companion. What would you like to explore today?",
            false
        )
    ),
    val input: String = "",
    val isLoading: Boolean = false,
    val isConnected: Boolean = false
)