package com.mimo.companion

import android.app.Application
import android.content.Context
import com.mimo.companion.data.local.MimoDatabase
import com.mimo.companion.data.prefs.AppSettings
import com.mimo.companion.data.prefs.SettingsStore
import com.mimo.companion.data.remote.ClientConfig
import com.mimo.companion.data.remote.MimoClient
import com.mimo.companion.data.repository.AgentRepository
import com.mimo.companion.data.repository.AuthRepository
import com.mimo.companion.data.repository.ChatRepository
import com.mimo.companion.data.repository.MemoryRepository
import com.mimo.companion.data.repository.SettingsRepository
import com.mimo.companion.device.NotificationCenter
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking

/**
 * One wiring point for the whole app. Deliberately hand-rolled instead of Hilt: there are eleven
 * objects, they are all cheap, and a compile-time DI graph would buy nothing a reader of this file
 * cannot see in ten lines.
 */
class AppContainer(private val context: Context) {

    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    val settingsStore = SettingsStore(context)

    /**
     * The client reads its address and token from here on every call. It is loaded synchronously
     * once at startup so the first screen cannot race the settings read; afterwards the collector
     * below keeps it current, which is what makes "change the address" work without a restart.
     */
    @Volatile
    private var snapshot: AppSettings = runBlocking { settingsStore.current() }

    val settings = SettingsRepository(settingsStore)

    val client = MimoClient { ClientConfig(snapshot.backendUrl, snapshot.token) }

    val database: MimoDatabase = MimoDatabase.get(context)

    val auth = AuthRepository(client, settingsStore)
    val chat = ChatRepository(client, database)
    val memory = MemoryRepository(client)
    val agents = AgentRepository(client)

    val notifications = NotificationCenter(context, client, database, scope)

    val connection = com.mimo.companion.device.ConnectionMonitor(client, scope)

    init {
        scope.launch {
            settingsStore.settings.collect { current -> snapshot = current }
        }
        connection.start(isPaired = { snapshot.isPaired })
        notifications.start(isPaired = { snapshot.isPaired }, settingsProvider = { snapshot })
    }

    fun currentSettings(): AppSettings = snapshot
}

class MimoApp : Application() {
    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
    }
}
