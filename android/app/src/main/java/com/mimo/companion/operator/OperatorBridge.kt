package com.mimo.companion.operator

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

data class OperatorState(
    val connected: Boolean = false,
    val packageName: String = "",
    val elementCount: Int = 0,
    val lastAction: String = "",
    val lastResult: String = "",
    val log: List<String> = emptyList()
)

/**
 * The one place the UI watches the operator and the operator reports to. Kept as a process-wide
 * object because an AccessibilityService has no lifetime a ViewModel can bind to — the service can
 * be running while no screen of the app is open, which is exactly the point of it.
 */
object OperatorBridge {

    private val _state = MutableStateFlow(OperatorState())
    val state: StateFlow<OperatorState> = _state.asStateFlow()

    fun attach() {
        _state.value = _state.value.copy(connected = true)
    }

    fun detach() {
        _state.value = OperatorState(connected = false)
    }

    /** Only the window changed; the tree has not been read yet. */
    fun window(packageName: String) {
        if (_state.value.packageName != packageName) {
            _state.value = _state.value.copy(packageName = packageName)
        }
    }

    fun screenRead(snapshot: ScreenSnapshot) {
        _state.value = _state.value.copy(
            packageName = snapshot.packageName,
            elementCount = snapshot.elements.size
        )
    }

    fun action(name: String, result: ActionResult) {
        val line = "${if (result.ok) "✓" else "✗"} $name — ${result.detail}"
        _state.value = _state.value.copy(
            lastAction = name,
            lastResult = result.detail,
            log = (listOf(line) + _state.value.log).take(40)
        )
    }
}
