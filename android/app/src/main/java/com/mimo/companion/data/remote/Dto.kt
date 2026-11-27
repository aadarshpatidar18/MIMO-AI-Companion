package com.mimo.companion.data.remote

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.jsonPrimitive

/**
 * One JSON configuration for every wire type. [ignoreUnknownKeys] matters more than usual:
 * the backend is versioned independently of the app, and an extra field added there must never
 * crash a phone that has not been updated yet.
 */
val MimoJson: Json = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
    encodeDefaults = true
    isLenient = false
}

@Serializable
data class DeviceDto(
    val id: String = "",
    val name: String = "",
    val kind: String = "",
    val scopes: List<String> = emptyList(),
    @SerialName("last_seen") val lastSeen: String? = null,
    @SerialName("created_at") val createdAt: String? = null,
    val revoked: Int = 0
)

@Serializable
data class PairRequest(
    val code: String,
    val name: String,
    val kind: String = "android"
)

@Serializable
data class PairResponse(val device: DeviceDto, val token: String)

@Serializable
data class TokenResponse(val token: String)

@Serializable
data class DevicesResponse(val devices: List<DeviceDto> = emptyList(), val count: Int = 0)

@Serializable
data class AuthStatus(
    @SerialName("require_auth") val requireAuth: Boolean = false,
    @SerialName("paired_devices") val pairedDevices: Int = 0,
    @SerialName("pairing_window_open") val pairingWindowOpen: Boolean = false
)

@Serializable
data class ConversationDto(
    val id: String,
    val title: String = "",
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
    @SerialName("device_id") val deviceId: String? = null,
    val archived: Int = 0,
    @SerialName("message_count") val messageCount: Int = 0,
    @SerialName("last_message") val lastMessage: String? = null
)

@Serializable
data class ConversationsResponse(
    val conversations: List<ConversationDto> = emptyList(),
    val count: Int = 0
)

@Serializable
data class MessageDto(
    val id: Long,
    @SerialName("conversation_id") val conversationId: String,
    val role: String,
    val content: String,
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("device_id") val deviceId: String? = null
)

@Serializable
data class MessagesResponse(
    val messages: List<MessageDto> = emptyList(),
    val count: Int = 0,
    @SerialName("next_after_id") val nextAfterId: Long = 0
)

@Serializable
data class NewConversationBody(val title: String = "")

@Serializable
data class ChatBody(
    val message: String,
    @SerialName("conversation_id") val conversationId: String,
    @SerialName("session_id") val sessionId: String? = null
)

@Serializable
data class ChatResponse(
    val success: Boolean = false,
    @SerialName("conversation_id") val conversationId: String? = null,
    val response: String = "",
    val intent: String? = null,
    @SerialName("device_id") val deviceId: String? = null,
    @SerialName("user_message_id") val userMessageId: Long? = null,
    @SerialName("assistant_message_id") val assistantMessageId: Long? = null,
    @SerialName("created_at") val createdAt: String? = null
)

@Serializable
data class MemoryDto(
    val id: Int,
    val content: String = "",
    val category: String = "",
    val importance: Int = 3,
    @SerialName("access_count") val accessCount: Int = 0,
    @SerialName("last_used") val lastUsed: String? = null,
    @SerialName("created_at") val createdAt: String? = null
)

@Serializable
data class MemoryResponse(val memories: List<MemoryDto> = emptyList(), val count: Int = 0)

@Serializable
data class MemoryBody(val content: String, val category: String? = null)

@Serializable
data class ForgetBody(val keyword: String)

@Serializable
data class MemoryPatchBody(
    val content: String? = null,
    val category: String? = null,
    val importance: Int? = null
)

@Serializable
data class AgentTaskDto(
    val id: String,
    val status: String = "",
    val goal: String = "",
    val agent: String? = null,
    @SerialName("agent_key") val agentKey: String? = null,
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("finished_at") val finishedAt: String? = null,
    @SerialName("started_at") val startedAt: String? = null,
    val error: JsonElement? = null,
    val result: JsonElement? = null,
    val pending: JsonElement? = null,
    val steps: JsonElement? = null
) {
    /** `pending` is a confirmation request when the engine is waiting on the user. */
    val needsApproval: Boolean
        get() = status == "awaiting_confirmation" || status == "waiting_confirmation" ||
            (pending != null && pending !is kotlinx.serialization.json.JsonNull)

    /** Which step is paused, so an approval can name it instead of "whatever is waiting now". */
    val pendingStepIndex: Int?
        get() = (pending as? kotlinx.serialization.json.JsonObject)
            ?.get("index")
            ?.let { (it as? kotlinx.serialization.json.JsonPrimitive)?.content }
            ?.toIntOrNull()
}

@Serializable
data class TasksResponse(val tasks: List<AgentTaskDto> = emptyList())

@Serializable
data class TaskStartBody(val goal: String, @SerialName("agent") val agent: String? = null)

@Serializable
data class TaskStarted(val id: String, val status: String = "", val agent: String? = null)

@Serializable
data class HealthResponse(val status: String = "")

@Serializable
data class DetailResponse(val detail: JsonElement? = null)

/** The FastAPI error body is `{"detail": "..."}` or `{"detail": [{...}]}`; both must read well. */
fun detailText(body: String?): String? {
    if (body.isNullOrBlank()) return null
    return runCatching {
        val element = MimoJson.parseToJsonElement(body)
        val detail = (element as? kotlinx.serialization.json.JsonObject)?.get("detail")
        when (detail) {
            null -> null
            is kotlinx.serialization.json.JsonArray ->
                detail.joinToString("; ") { it.jsonPrimitive.content }
            else -> detail.jsonPrimitive.content
        }
    }.getOrNull()
}
