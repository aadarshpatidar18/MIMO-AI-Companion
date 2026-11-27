package com.mimo.companion.data.local

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase

/**
 * Schema version 1 is the first schema that ever shipped, so there is no migration to write yet.
 * The exported schema in `app/schemas` is the baseline every later migration is diffed against —
 * that is what keeps a future upgrade from destroying the user's local history.
 */
@Database(
    entities = [ConversationEntity::class, MessageEntity::class, NotifiedTaskEntity::class],
    version = 1,
    exportSchema = true
)
abstract class MimoDatabase : RoomDatabase() {

    abstract fun conversations(): ConversationDao
    abstract fun messages(): MessageDao
    abstract fun notifiedTasks(): NotifiedTaskDao

    companion object {
        @Volatile
        private var instance: MimoDatabase? = null

        fun get(context: Context): MimoDatabase = instance ?: synchronized(this) {
            instance ?: Room.databaseBuilder(
                context.applicationContext,
                MimoDatabase::class.java,
                "mimo-companion.db"
            )
                // Local history is a cache of the backend, not the only copy: if a future schema
                // step is ever missing, starting clean loses conversation text the server still
                // has. It never touches the backend's own database.
                .fallbackToDestructiveMigration(dropAllTables = true)
                .build()
                .also { instance = it }
        }
    }
}
