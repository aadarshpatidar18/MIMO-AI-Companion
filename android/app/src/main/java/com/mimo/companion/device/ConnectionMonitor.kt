package com.mimo.companion.device

import com.mimo.companion.data.remote.ApiException
import com.mimo.companion.data.remote.MimoClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.time.Instant

enum class LinkState { UNPAIRED, CONNECTING, ONLINE, OFFLINE, UNAUTHORISED }

data class ConnectionStatus(
    val state: LinkState = LinkState.CONNECTING,
    val detail: String = "",
    val lastOkAt: String? = null,
    val consecutiveFailures: Int = 0
) {
    val isOnline: Boolean get() = state == LinkState.ONLINE
}

/**
 * Keeps one honest opinion of whether the backend is reachable, and backs off instead of
 * hammering it. Reconnect is automatic: 2 s, 4 s, 8 s … capped at 30 s, reset on the first
 * success. Nothing here is a promise that the *model* is up — `/health` answers even when every
 * provider is down, which is deliberate: those are different failures with different messages.
 */
class ConnectionMonitor(
    private val client: MimoClient,
    private val scope: CoroutineScope
) {
    private val _status = MutableStateFlow(ConnectionStatus())
    val status: StateFlow<ConnectionStatus> = _status.asStateFlow()

    @Volatile
    private var running = false

    fun start(isPaired: () -> Boolean) {
        if (running) return
        running = true
        scope.launch {
            var backoffMs = 2_000L
            while (running) {
                if (!isPaired()) {
                    _status.value = ConnectionStatus(LinkState.UNPAIRED, "Not paired with a MIMO PC yet")
                    delay(5_000)
                    continue
                }
                _status.value = _status.value.copy(state = LinkState.CONNECTING)
                val ok = client.health()
                if (ok) {
                    backoffMs = 2_000L
                    _status.value = ConnectionStatus(LinkState.ONLINE, "Connected",
                        Instant.now().toString(), 0)
                    delay(6_000)
                } else {
                    backoffMs = (backoffMs * 2).coerceAtMost(30_000L)
                    _status.value = ConnectionStatus(
                        LinkState.OFFLINE,
                        "No answer from MIMO",
                        _status.value.lastOkAt,
                        _status.value.consecutiveFailures + 1
                    )
                    delay(backoffMs)
                }
            }
        }
    }

    fun stop() { running = false }

    /** The backend rejected the token (401/403) — re-pairing is the only fix. */
    fun markUnauthorised(message: String) {
        _status.value = ConnectionStatus(LinkState.UNAUTHORISED, message, _status.value.lastOkAt, 0)
    }

    fun noteFailure(e: ApiException) {
        when {
            e.isUnauthorized -> markUnauthorised(e.message)
            e.isOffline -> _status.value = _status.value.copy(
                state = LinkState.OFFLINE,
                detail = e.message,
                consecutiveFailures = _status.value.consecutiveFailures + 1
            )
        }
    }

    suspend fun probeOnce(): Boolean {
        val ok = client.health()
        _status.value = if (ok) {
            ConnectionStatus(LinkState.ONLINE, "Connected", Instant.now().toString(), 0)
        } else {
            ConnectionStatus(LinkState.OFFLINE, "No answer from MIMO", _status.value.lastOkAt,
                _status.value.consecutiveFailures + 1)
        }
        return ok
    }
}
