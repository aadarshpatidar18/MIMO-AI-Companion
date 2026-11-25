package com.mimo.companion.data.repository

import com.mimo.companion.data.remote.ApiService

class MimoRepository {

    suspend fun sendMessage(
        message: String,
        sessionId: String
    ): String {
        return ApiService.sendMessage(message, sessionId)
    }

    suspend fun checkConnection(): Boolean {
        return ApiService.checkConnection()
    }
}