package com.mimo.companion.data.remote

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.DeserializationStrategy
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * What the client needs to talk to this MIMO backend. Read on every call rather than captured in
 * the constructor: the user can change the address or re-pair without the app being restarted.
 */
data class ClientConfig(val baseUrl: String, val token: String?)

class ApiException(
    val status: Int,
    override val message: String,
    val body: String? = null
) : Exception(message) {
    val isUnauthorized: Boolean get() = status == 401 || status == 403
    val isOffline: Boolean get() = status == 0
    val isConflict: Boolean get() = status == 409
}

/**
 * A thin, honest HTTP layer: one place that adds the bearer token, maps error bodies to a message
 * the user can read, and turns "no socket" into a distinct offline state instead of a crash.
 *
 * Timeouts are deliberately asymmetric. Reads are long because a chat turn waits on a local model;
 * connects are short because a wrong address on the LAN should fail while the user is still
 * looking at the screen.
 */
class MimoClient(private val config: () -> ClientConfig) {

    private val json = MimoJson
    private val mediaJson = "application/json; charset=utf-8".toMediaType()

    private val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(180, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .callTimeout(200, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()

    private fun url(path: String): String {
        val base = config().baseUrl.trim().trimEnd('/')
        val suffix = if (path.startsWith("/")) path else "/$path"
        return base + suffix
    }

    suspend fun <T> get(path: String, decoder: DeserializationStrategy<T>): T =
        decode(send("GET", path, null), decoder)

    suspend fun <T> post(path: String, body: String?, decoder: DeserializationStrategy<T>): T =
        decode(send("POST", path, body ?: "{}"), decoder)

    suspend fun <T> put(path: String, body: String?, decoder: DeserializationStrategy<T>): T =
        decode(send("PUT", path, body ?: "{}"), decoder)

    suspend fun <T> patch(path: String, body: String?, decoder: DeserializationStrategy<T>): T =
        decode(send("PATCH", path, body ?: "{}"), decoder)

    suspend fun delete(path: String, body: String? = null): Unit {
        send("DELETE", path, body)
    }

    suspend fun deleteJson(path: String): Unit {
        send("DELETE", path, null)
    }

    /** No token, no decode: used for the reachability probe and for pairing. */
    suspend fun health(): Boolean = try {
        val text = send("GET", "/health", null, authenticated = false)
        val health = decode(text, HealthResponse.serializer())
        health.status.equals("ok", ignoreCase = true) || health.status.isNotEmpty()
    } catch (e: ApiException) {
        false
    }

    private fun <T> decode(text: String, decoder: DeserializationStrategy<T>): T {
        if (text.isBlank()) {
            throw ApiException(500, "MIMO answered with an empty body.")
        }
        return try {
            json.decodeFromString(decoder, text)
        } catch (e: Exception) {
            throw ApiException(500, "MIMO sent a response this app could not read.", text)
        }
    }

    private suspend fun send(
        method: String,
        path: String,
        body: String?,
        authenticated: Boolean = true
    ): String = withContext(Dispatchers.IO) {
        val builder = Request.Builder().url(url(path))
        val token = config().token
        if (authenticated && !token.isNullOrBlank()) {
            builder.header("Authorization", "Bearer $token")
        }
        builder.header("Accept", "application/json")
        val payload = body?.toRequestBody(mediaJson)
        when (method) {
            "GET" -> builder.get()
            "DELETE" -> if (payload == null) builder.delete() else builder.delete(payload)
            "POST" -> builder.post(payload ?: "{}".toRequestBody(mediaJson))
            "PUT" -> builder.put(payload ?: "{}".toRequestBody(mediaJson))
            "PATCH" -> builder.patch(payload ?: "{}".toRequestBody(mediaJson))
            else -> error("Unsupported method $method")
        }
        val request = builder.build()
        val call = http.newCall(request)
        try {
            call.execute().use { response ->
                val text = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    val detail = detailText(text) ?: "MIMO answered ${response.code}."
                    throw ApiException(response.code, detail, text)
                }
                text
            }
        } catch (e: ApiException) {
            throw e
        } catch (e: IOException) {
            throw ApiException(0, "Can't reach MIMO at ${config().baseUrl}. ${e.message.orEmpty()}".trim())
        }
    }
}
