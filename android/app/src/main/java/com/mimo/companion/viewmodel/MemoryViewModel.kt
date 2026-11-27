package com.mimo.companion.viewmodel

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.mimo.companion.MimoApp
import com.mimo.companion.data.remote.ApiException
import com.mimo.companion.data.remote.MemoryDto
import kotlinx.coroutines.launch

class MemoryViewModel(app: Application) : AndroidViewModel(app) {

    private val container = (app as MimoApp).container

    var memories by mutableStateOf<List<MemoryDto>>(emptyList())
        private set
    var query by mutableStateOf("")
        private set
    var loading by mutableStateOf(false)
        private set
    var notice by mutableStateOf<String?>(null)
        private set

    init { refresh() }

    fun onQuery(value: String) { query = value }

    fun refresh() {
        loading = true
        viewModelScope.launch {
            try {
                memories = container.memory.search(query)
            } catch (e: ApiException) {
                notice = e.message
            } finally {
                loading = false
            }
        }
    }

    fun remember(content: String, category: String?) {
        val text = content.trim()
        if (text.isEmpty()) return
        viewModelScope.launch {
            runCatching { container.memory.remember(text, category?.ifBlank { null }) }
                .onSuccess { refresh() }
                .onFailure { notice = it.message }
        }
    }

    fun correct(id: Int, content: String?, importance: Int?) {
        viewModelScope.launch {
            runCatching { container.memory.correct(id, content, importance = importance) }
                .onSuccess { refresh() }
                .onFailure { notice = it.message }
        }
    }

    fun forget(keyword: String) {
        val clean = keyword.trim()
        if (clean.isEmpty()) return
        viewModelScope.launch {
            runCatching { container.memory.forget(clean) }
                .onSuccess { refresh() }
                .onFailure { notice = it.message }
        }
    }

    fun dismiss() { notice = null }
}
