package com.mimo.companion.data.local

import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * The phone keeps its own copy of the conversation so the app opens instantly and keeps working
 * when the laptop is asleep. The backend remains the authority for message ids; [remoteId] is the
 * join key back to it, and is null until the server has accepted the message.
 */
@Entity(tableName = "conversations")
data class ConversationEntity(
    @PrimaryKey val id: String,
    val title: String,
    val createdAt: String?,
    val updatedAt: String?,
    val messageCount: Int = 0,
    val lastMessage: String? = null,
    /** False when this row exists only on the phone (created offline, not yet pushed). */
    val synced: Boolean = true,
    val deleted: Boolean = false
)

enum class MessageStatus { PENDING, SENT, FAILED }

@Entity(
    tableName = "messages",
    foreignKeys = [
        ForeignKey(
            entity = ConversationEntity::class,
            parentColumns = ["id"],
            childColumns = ["conversationId"],
            onDelete = ForeignKey.CASCADE
        )
    ],
    indices = [
        Index(value = ["conversationId", "createdAt"]),
        Index(value = ["conversationId", "remoteId"], unique = true)
    ]
)
data class MessageEntity(
    @PrimaryKey(autoGenerate = true) val localId: Long = 0,
    val remoteId: Long? = null,
    val conversationId: String,
    /** "user" or "assistant" — the backend's own vocabulary. */
    val role: String,
    val content: String,
    /** ISO-8601, UTC. Displayed in the phone's zone by the UI. */
    val createdAt: String,
    val status: String = MessageStatus.SENT.name
)

/** One row per device-level signal the notification centre has already shown, so it never repeats. */
@Entity(tableName = "notified_tasks")
data class NotifiedTaskEntity(
    @PrimaryKey val taskId: String,
    val status: String,
    val notifiedAt: String
)
