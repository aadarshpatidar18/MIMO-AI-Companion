package com.mimo.companion.data.repository

import com.mimo.companion.data.prefs.SettingsStore
import com.mimo.companion.data.remote.AuthStatus
import com.mimo.companion.data.remote.DeviceDto
import com.mimo.companion.data.remote.DevicesResponse
import com.mimo.companion.data.remote.MimoClient
import com.mimo.companion.data.remote.MimoJson
import com.mimo.companion.data.remote.PairRequest
import com.mimo.companion.data.remote.PairResponse
import com.mimo.companion.data.remote.TokenResponse

/**
 * Pairing is the only way this phone gets a token: the PC shows a single-use code, the phone
 * trades it in here, and the token is stored once. No password is ever accepted or stored, and the
 * code is not kept after a successful exchange.
 */
class AuthRepository(
    private val client: MimoClient,
    private val settings: SettingsStore
) {
    suspend fun status(): AuthStatus? = runCatching {
        client.get("/auth/status", AuthStatus.serializer())
    }.getOrNull()

    suspend fun pair(code: String, deviceName: String, kind: String = "android"): DeviceDto {
        val trimmed = code.trim().uppercase()
        require(trimmed.length >= 4) { "That pairing code looks too short." }
        val body = MimoJson.encodeToString(
            PairRequest.serializer(),
            PairRequest(code = trimmed, name = deviceName, kind = kind)
        )
        val response = client.post("/auth/pair", body, PairResponse.serializer())
        settings.savePairing(
            token = response.token,
            deviceId = response.device.id,
            deviceName = response.device.name.ifBlank { deviceName },
            kind = response.device.kind.ifBlank { kind }
        )
        return response.device
    }

    suspend fun me(): DeviceDto = client.get("/auth/me", DeviceDto.serializer())

    suspend fun devices(): List<DeviceDto> =
        client.get("/devices", DevicesResponse.serializer()).devices

    /** Replaces the stored token. A rotated token invalidates the old one, so this cannot be undone. */
    suspend fun rotate(): String {
        val response = client.post("/auth/token/rotate", null, TokenResponse.serializer())
        val current = settings.current()
        settings.savePairing(
            token = response.token,
            deviceId = current.deviceId.orEmpty(),
            deviceName = current.deviceName,
            kind = current.deviceKind
        )
        return response.token
    }

    suspend fun revokeSelf(deviceId: String) {
        client.delete("/devices/$deviceId")
        settings.clearPairing()
    }

    suspend fun forgetDevice() {
        settings.clearPairing()
    }
}
