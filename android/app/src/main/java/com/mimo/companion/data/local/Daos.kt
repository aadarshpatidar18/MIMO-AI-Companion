package com.mimo.companion.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.Query
import androidx.room.Transaction
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow

@Dao
interface ConversationDao {

    @Query("SELECT * FROM conversations WHERE deleted = 0 ORDER BY COALESCE(updatedAt, createdAt) DESC")
    fun observeAll(): Flow<List<ConversationEntity>>

    @Query("SELECT * FROM conversations WHERE id = :id")
    suspend fun byId(id: String): ConversationEntity?

    @Upsert
    suspend fun upsertAll(items: List<ConversationEntity>)

    @Upsert
    suspend fun upsert(item: ConversationEntity)

    @Query("UPDATE conversations SET deleted = 1 WHERE id = :id")
    suspend fun markDeleted(id: String)

    @Query("DELETE FROM conversations WHERE id = :id AND synced = 0")
    suspend fun deleteLocalOnly(id: String)

    @Query("UPDATE conversations SET title = :title WHERE id = :id")
    suspend fun rename(id: String, title: String)

    @Query("SELECT * FROM conversations WHERE deleted = 0")
    suspend fun all(): List<ConversationEntity>

    @Query("SELECT * FROM conversations WHERE synced = 0 AND deleted = 0")
    suspend fun unsynced(): List<ConversationEntity>

    @Query("DELETE FROM conversations WHERE id = :id")
    suspend fun delete(id: String)

    @Query("SELECT * FROM conversations WHERE deleted = 1")
    suspend fun pendingDeletions(): List<ConversationEntity>
}

@Dao
interface MessageDao {

    @Query("SELECT * FROM messages WHERE conversationId = :conversationId ORDER BY createdAt ASC, localId ASC")
    fun observeFor(conversationId: String): Flow<List<MessageEntity>>

    @Query("SELECT * FROM messages WHERE conversationId = :conversationId ORDER BY createdAt ASC, localId ASC")
    suspend fun forConversation(conversationId: String): List<MessageEntity>

    @Query("SELECT COALESCE(MAX(remoteId), 0) FROM messages WHERE conversationId = :conversationId")
    suspend fun maxRemoteId(conversationId: String): Long

    @Upsert
    suspend fun upsertAll(items: List<MessageEntity>)

    @Insert
    suspend fun insertAll(items: List<MessageEntity>)

    @Upsert
    suspend fun upsert(item: MessageEntity)

    @Insert
    suspend fun insert(item: MessageEntity): Long

    @Query("UPDATE messages SET status = :status WHERE localId = :localId")
    suspend fun setStatus(localId: Long, status: String)

    @Query("UPDATE messages SET remoteId = :remoteId, status = :status, createdAt = COALESCE(createdAt, :createdAt) WHERE localId = :localId")
    suspend fun markSent(localId: Long, remoteId: Long?, status: String, createdAt: String)

    @Query("SELECT * FROM messages WHERE conversationId = :conversationId AND status = 'PENDING' ORDER BY localId ASC")
    suspend fun pending(conversationId: String): List<MessageEntity>

    @Query("SELECT COUNT(*) FROM messages WHERE conversationId = :conversationId AND status = 'PENDING'")
    fun pendingCount(conversationId: String): Flow<Int>

    @Query("UPDATE messages SET conversationId = :to WHERE conversationId = :from")
    suspend fun moveConversation(from: String, to: String)

    @Query("DELETE FROM messages WHERE remoteId = :remoteId AND conversationId = :conversationId")
    suspend fun deleteRemoteCopy(conversationId: String, remoteId: Long)
}

@Dao
interface NotifiedTaskDao {
    @Query("SELECT * FROM notified_tasks WHERE taskId = :taskId")
    suspend fun byId(taskId: String): NotifiedTaskEntity?

    @Upsert
    suspend fun upsert(item: NotifiedTaskEntity)

    @Query("DELETE FROM notified_tasks WHERE notifiedAt < :cutoff")
    suspend fun pruneBefore(cutoff: String)
}
