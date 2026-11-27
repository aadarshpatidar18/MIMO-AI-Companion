package com.mimo.companion.viewmodel

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.mimo.companion.operator.MimoAccessibilityService
import com.mimo.companion.operator.OperatorBridge
import com.mimo.companion.operator.ScreenAnalysis
import com.mimo.companion.operator.ScreenAnalyzer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class OperatorViewModel(app: Application) : AndroidViewModel(app) {

    private val analyzer = ScreenAnalyzer()

    val status = OperatorBridge.state

    var analysis by mutableStateOf<ScreenAnalysis?>(null)
        private set
    var busy by mutableStateOf(false)
        private set
    var notice by mutableStateOf<String?>(null)
        private set
    var target by mutableStateOf("")
        private set
    var text by mutableStateOf("")
        private set

    fun onTarget(value: String) { target = value }
    fun onText(value: String) { text = value }
    fun dismiss() { notice = null }

    private fun service(): MimoAccessibilityService? {
        val running = MimoAccessibilityService.instance
        if (running == null) notice = "Turn on MIMO in Settings → Accessibility first."
        return running
    }

    fun readScreen() {
        val service = service() ?: return
        busy = true
        viewModelScope.launch {
            try {
                val snapshot = withContext(Dispatchers.Main) { service.readScreen() }
                analysis = analyzer.analyse(snapshot)
            } finally {
                busy = false
            }
        }
    }

    fun tap() {
        val label = target.trim()
        if (label.isEmpty()) { notice = "Name the element to tap."; return }
        val service = service() ?: return
        viewModelScope.launch {
            val result = withContext(Dispatchers.Main) { service.tap(label) }
            notice = result.detail
            readScreen()
        }
    }

    fun type() {
        val label = target.trim()
        val content = text
        if (label.isEmpty() || content.isEmpty()) { notice = "Name the field and the text."; return }
        val service = service() ?: return
        viewModelScope.launch {
            val result = withContext(Dispatchers.Main) { service.typeInto(label, content) }
            notice = result.detail
            readScreen()
        }
    }

    fun scroll(down: Boolean) {
        val service = service() ?: return
        viewModelScope.launch {
            val result = withContext(Dispatchers.Main) { service.scroll(down) }
            notice = result.detail
            readScreen()
        }
    }

    fun back() {
        val service = service() ?: return
        viewModelScope.launch {
            val result = withContext(Dispatchers.Main) { service.back() }
            notice = result.detail
            readScreen()
        }
    }
}
