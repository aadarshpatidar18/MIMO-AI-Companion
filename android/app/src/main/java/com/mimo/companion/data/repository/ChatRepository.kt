package com.mimo.companion.data.repository

import com.mimo.companion.data.local.ConversationEntity
import com.mimo.companion.data.local.MessageEntity
import com.mimo.companion.data.local.MessageStatus
import com.mimo.companion.data.local.MimoDatabase
import com.mimo.companion.data.remote.ApiException
import com.mimo.companion.data.remote.ChatBody
import com.mimo.companion.data.remote.ChatResponse
import com.mimo.companion.data.remote.ConversationDto
import com.mimo.companion.data.remote.ConversationsResponse
import com.mimo.companion.data.remote.MessageDto
import com.mimo.companion.data.remote.MessagesResponse
import com.mimo.companion.data.remote.MimoClient
import com.mimo.companion.data.remote.MimoJson
import com.mimo.companion.data.remote.NewConversationBody
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.time.Instant
import java.util.UUID

sealed interface SendOutcome {
    /** The answer is carried so callers can speak it; the repository does not know about voices. */
    data class Sent(val answer: String) : SendOutcome
    /** Accepted locally and will be sent when MIMO is reachable again. */
    data object Queued : SendOutcome
    data class Failed(val message: String) : SendOutcome
}

/**
 * Conversations live twice: on the backend (the shared history every paired device reads) and in
 * Room on this phone (so the app opens with the last conversation already on screen, and works
 * with the laptop asleep).
 *
 * The rule that keeps them in step: the server owns message ids. A message this phone sends is
 * written locally as PENDING first, then posted; the reply carries the ids the server assigned, so
 * the local row is stamped with its real id and nothing is ever duplicated by a later sync.
 * A message sent while offline stays PENDING and is retried, in order, when the link returns.
 */
class ChatRepository(
    private val client: MimoClient,
    private val db: MimoDatabase,
    private val now: () -> String = { Instant.now().toString() }
) {
    private val conversationsDao = db.conversations()
    private val messagesDao = db.messages()

    val conversations: Flow<List<ConversationEntity>> = conversationsDao.observeAll()

    private val _activeConversation = MutableStateFlow<String?>(null)

    /** Followed by the UI: a conversation created offline is replaced by its server id on first send. */
    val activeConversation: StateFlow<String?> = _activeConversation.asStateFlow()

    fun messages(conversationId: String): Flow<List<MessageEntity>> =
        messagesDao.observeFor(conversationId)

    fun pendingCount(conversationId: String): Flow<Int> = messagesDao.pendingCount(conversationId)

    fun open(conversationId: String?) {
        _activeConversation.value = conversationId
    }

    suspend fun conversation(id: String): ConversationEntity? = conversationsDao.byId(id)

    // ---------------------------------------------------------------- reading

    suspend fun refreshConversations() {
        val remote = client.get("/conversations?limit=100", ConversationsResponse.serializer())
            .conversations
        val local = conversationsDao.all().associateBy { it.id }
        val rows = remote.map { dto ->
            val existing = local[dto.id]
            dto.toEntity(
                keepTitle = existing?.title?.takeIf { it.isNotBlank() && dto.title.isBlank() }
            )
        }
        if (rows.isNotEmpty()) conversationsDao.upsertAll(rows)
        flushPendingDeletions()
    }

    /** Pulls everything newer than the last message this phone has seen for that conversation. */
    suspend fun syncMessages(conversationId: String): Int {
        val after = messagesDao.maxRemoteId(conversationId)
        val response = client.get(
            "/conversations/$conversationId/messages?after_id=$after&limit=200",
            MessagesResponse.serializer()
        )
        if (response.messages.isEmpty()) return 0
        // Delete any local copy of the same server rows first: the phone's copy may be the
        // optimistic one that has no timestamp yet, and REPLACE-by-unique-index would leave two.
        response.messages.forEach { messagesDao.deleteRemoteCopy(conversationId, it.id) }
        messagesDao.insertAll(response.messages.map { it.toEntity() })
        return response.messages.size
    }

    // ---------------------------------------------------------------- writing

    suspend fun createConversation(title: String = ""): String {
        // Online first: the shared history is the authority, and an id that already exists on the
        // server needs no migration later. Offline, the conversation is created locally and is
        // pushed on the first successful send.
        return try {
            val body = MimoJson.encodeToString(NewConversationBody.serializer(), NewConversationBody(title))
            val dto = client.post("/conversations", body, ConversationDto.serializer())
            conversationsDao.upsert(dto.toEntity())
            dto.id
        } catch (e: ApiException) {
            if (!e.isOffline) throw e
            val id = "local-${UUID.randomUUID()}"
            conversationsDao.upsert(
                ConversationEntity(
                    id = id,
                    title = title.ifBlank { "New conversation" },
                    createdAt = now(),
                    updatedAt = now(),
                    synced = false
                )
            )
            id
        }
    }

    suspend fun renameConversation(conversationId: String, title: String) {
        val clean = title.trim().take(120)
        if (clean.isBlank()) return
        conversationsDao.rename(conversationId, clean)
        val local = conversationsDao.byId(conversationId) ?: return
        if (local.synced) {
            runCatching {
                val body = MimoJson.encodeToString(NewConversationBody.serializer(), NewConversationBody(clean))
                client.patch("/conversations/$conversationId", body, ConversationDto.serializer())
            }
        }
    }

    suspend fun deleteConversation(conversationId: String) {
        val local = conversationsDao.byId(conversationId)
        if (local != null && local.synced) {
            try {
                client.delete("/conversations/$conversationId")
            } catch (e: ApiException) {
                // Offline: remember the deletion and finish it on the next successful sync.
                if (e.isOffline) {
                    // Hide it now, finish the deletion on the next successful sync.
                    conversationsDao.markDeleted(conversationId)
                    return
                }
                if (!e.isUnauthorized) throw e
            }
        }
        conversationsDao.delete(conversationId)
        if (_activeConversation.value == conversationId) _activeConversation.value = null
    }

    /**
     * Sends one turn. [conversationId] may be a local id; it is upgraded to the server's id before
     * the message is posted, and the caller is told the new id through [activeConversation].
     */
    suspend fun send(conversationId: String, text: String): SendOutcome {
        val trimmed = text.trim()
        if (trimmed.isBlank()) return SendOutcome.Failed("That message is empty.")

        val localId = messagesDao.insert(
            MessageEntity(
                conversationId = conversationId,
                role = "user",
                content = trimmed,
                createdAt = now(),
                status = MessageStatus.PENDING.name
            )
        )
        return deliver(conversationId, localId, trimmed)
    }

    /** Retries every queued message of a conversation, oldest first. Stops at the first failure. */
    suspend fun retryQueued(conversationId: String): Int {
        var delivered = 0
        for (pending in messagesDao.pending(conversationId)) {
            val outcome = deliver(conversationId, pending.localId, pending.content)
            if (outcome !is SendOutcome.Sent) break
            delivered++
        }
        return delivered
    }

    private suspend fun deliver(conversationId: String, localId: Long, text: String): SendOutcome {
        val remoteId = try {
            ensureRemoteConversation(conversationId)
        } catch (e: ApiException) {
            messagesDao.setStatus(localId, MessageStatus.FAILED.name)
            return SendOutcome.Failed(e.message)
        } catch (e: IllegalStateException) {
            messagesDao.setStatus(localId, MessageStatus.FAILED.name)
            return SendOutcome.Failed(e.message.orEmpty())
        }

        val body = MimoJson.encodeToString(
            ChatBody.serializer(),
            ChatBody(message = text, conversationId = remoteId, sessionId = "android")
        )
        return try {
            val response = client.post("/chat", body, ChatResponse.serializer())
            val stamp = response.createdAt ?: now()
            if (response.userMessageId != null) {
                messagesDao.deleteRemoteCopy(remoteId, response.userMessageId)
                messagesDao.markSent(localId, response.userMessageId, MessageStatus.SENT.name, stamp)
            } else {
                messagesDao.markSent(localId, null, MessageStatus.SENT.name, stamp)
            }
            val answer = response.response.ifBlank { "(MIMO sent an empty answer)" }
            if (response.assistantMessageId != null) {
                messagesDao.deleteRemoteCopy(remoteId, response.assistantMessageId)
                messagesDao.insert(
                    MessageEntity(
                        remoteId = response.assistantMessageId,
                        conversationId = remoteId,
                        role = "assistant",
                        content = answer,
                        createdAt = stamp,
                        status = MessageStatus.SENT.name
                    )
                )
            } else {
                messagesDao.insert(
                    MessageEntity(
                        conversationId = remoteId,
                        role = "assistant",
                        content = answer,
                        createdAt = now(),
                        status = MessageStatus.SENT.name
                    )
                )
            }
            touchConversation(remoteId, text, answer)
            SendOutcome.Sent(answer)
        } catch (e: ApiException) {
            if (e.isOffline) {
                SendOutcome.Queued
            } else {
                messagesDao.setStatus(localId, MessageStatus.FAILED.name)
                SendOutcome.Failed(e.message)
            }
        }
    }

    /**
     * Creates the conversation on the server the first time a local one is used, then moves the
     * already-typed messages onto the real id. The caller follows [activeConversation] so the
     * screen it is on does not disappear under it.
     */
    private suspend fun ensureRemoteConversation(conversationId: String): String {
        val local = conversationsDao.byId(conversationId)
            ?: throw IllegalStateException("That conversation no longer exists.")
        if (local.synced) return conversationId

        val title = local.title.takeIf { it.isNotBlank() && it != "New conversation" } ?: ""
        val body = MimoJson.encodeToString(NewConversationBody.serializer(), NewConversationBody(title))
        val dto = client.post("/conversations", body, ConversationDto.serializer())
        conversationsDao.upsert(dto.toEntity(keepTitle = local.title))
        messagesDao.moveConversation(conversationId, dto.id)
        conversationsDao.delete(conversationId)
        if (_activeConversation.value == conversationId) _activeConversation.value = dto.id
        return dto.id
    }

    private suspend fun touchConversation(conversationId: String, question: String, answer: String) {
        val local = conversationsDao.byId(conversationId) ?: return
        conversationsDao.upsert(
            local.copy(
                title = local.title.ifBlank { autoTitle(question) },
                updatedAt = now(),
                lastMessage = answer,
                messageCount = local.messageCount + 2
            )
        )
    }

    private suspend fun flushPendingDeletions() {
        val pending = conversationsDao.pendingDeletions()
        if (pending.isEmpty()) return
        for (row in pending) {
            val ok = runCatching { client.delete("/conversations/${row.id}") }.isSuccess
            if (ok) conversationsDao.delete(row.id)
        }
    }

    companion object {
        /** The backend's own rule for naming a conversation from its first line. */
        fun autoTitle(question: String): String {
            val line = question.lineSequence().firstOrNull()?.trim().orEmpty()
            if (line.isEmpty()) return "New conversation"
            return if (line.length <= 60) line else line.take(57).trimEnd() + "…"
        }
    }
}

private fun ConversationDto.toEntity(keepTitle: String? = null): ConversationEntity = ConversationEntity(
    id = id,
    title = keepTitle?.takeIf { it.isNotBlank() } ?: title.ifBlank { "Conversation" },
    createdAt = createdAt,
    updatedAt = updatedAt,
    messageCount = messageCount,
    lastMessage = lastMessage,
    synced = true
)

private fun MessageDto.toEntity(): MessageEntity = MessageEntity(
    remoteId = id,
    conversationId = conversationId,
    role = role,
    content = content,
    createdAt = createdAt ?: Instant.now().toString(),
    status = MessageStatus.SENT.name
)
