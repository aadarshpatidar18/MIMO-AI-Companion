package com.mimo.companion

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

object ApiService {

    private const val BASE_URL = "http://192.168.0.151:8000"
    fun sendMessage(
        message: String,
        sessionId: String
    ): String {

        val url = URL("$BASE_URL/chat")
        val connection = url.openConnection() as HttpURLConnection

        try {
            connection.requestMethod = "POST"
            connection.connectTimeout = 15000
            connection.readTimeout = 120000
            connection.doOutput = true

            connection.setRequestProperty(
                "Content-Type",
                "application/json"
            )

            connection.setRequestProperty(
                "Accept",
                "application/json"
            )

            val requestBody = JSONObject().apply {
                put("message", message)
                put("session_id", sessionId)
            }

            connection.outputStream.use {
                it.write(requestBody.toString().toByteArray(Charsets.UTF_8))
            }

            val statusCode = connection.responseCode

            val responseStream = if (statusCode in 200..299) {
                connection.inputStream
            } else {
                connection.errorStream
            }

            val responseText = responseStream.bufferedReader().use {
                it.readText()
            }

            val responseJson = JSONObject(responseText)

            if (statusCode !in 200..299) {
                throw Exception(
                    responseJson.optString(
                        "detail",
                        "Server error: $statusCode"
                    )
                )
            }

            if (!responseJson.optBoolean("success")) {
                throw Exception("MIMO could not process your request.")
            }

            return responseJson.getString("response")

        } finally {
            connection.disconnect()
        }
    }

    fun checkConnection(): Boolean {
        val connection = URL("$BASE_URL/health")
            .openConnection() as HttpURLConnection

        return try {
            connection.requestMethod = "GET"
            connection.connectTimeout = 5000
            connection.readTimeout = 5000

            connection.responseCode == 200
        } finally {
            connection.disconnect()
        }
    }
}