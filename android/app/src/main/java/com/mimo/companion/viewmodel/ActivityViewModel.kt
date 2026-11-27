package com.mimo.companion.viewmodel

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.mimo.companion.MimoApp
import com.mimo.companion.data.remote.AgentTaskDto
import com.mimo.companion.data.remote.ApiException
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class ActivityViewModel(app: Application) : AndroidViewModel(app) {

    private val container = (app as MimoApp).container

    var tasks by mutableStateOf<List<AgentTaskDto>>(emptyList())
        private set
    var loading by mutableStateOf(false)
        private set
    var notice by mutableStateOf<String?>(null)
        private set
    var newGoal by mutableStateOf("")
        private set

    init {
        refresh()
        viewModelScope.launch {
            // The activity screen is a live view while it is open; it stops when the screen closes
            // because this view model is cleared with the destination.
            while (isActive) {
                delay(8_000)
                runCatching { tasks = container.agents.tasks() }
            }
        }
    }

    fun onGoal(value: String) { newGoal = value }

    fun dismiss() { notice = null }

    fun refresh() {
        loading = true
        viewModelScope.launch {
            try {
                tasks = container.agents.tasks()
            } catch (e: ApiException) {
                notice = e.message
            } finally {
                loading = false
            }
        }
    }

    fun start() {
        val goal = newGoal.trim()
        if (goal.isEmpty()) return
        newGoal = ""
        viewModelScope.launch {
            runCatching { container.agents.start(goal) }
                .onSuccess { refresh() }
                .onFailure { notice = it.message }
        }
    }

    fun cancel(id: String) {
        viewModelScope.launch {
            runCatching { container.agents.cancel(id) }
                .onSuccess { refresh() }
                .onFailure { notice = it.message }
        }
    }

    fun confirm(id: String, approve: Boolean) {
        viewModelScope.launch {
            runCatching { container.agents.confirm(id, approve) }
                .onSuccess { refresh() }
                .onFailure { notice = it.message }
        }
    }
}
