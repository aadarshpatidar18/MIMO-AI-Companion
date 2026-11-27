package com.mimo.companion.device

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.mimo.companion.MainActivity
import com.mimo.companion.MimoApp
import com.mimo.companion.R
import com.mimo.companion.data.local.MimoDatabase
import com.mimo.companion.data.local.NotifiedTaskEntity
import com.mimo.companion.data.prefs.AppSettings
import com.mimo.companion.data.remote.AgentTaskDto
import com.mimo.companion.data.remote.ApiException
import com.mimo.companion.data.remote.MimoClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.temporal.ChronoUnit

/**
 * Notifications are derived from polling the task list, not from a push service: MIMO runs on the
 * user's own PC on a home network, and adding a push dependency would mean sending task state to a
 * third party. The poll is cheap, only runs while the phone believes the backend is reachable, and
 * remembers what it already showed so a restart does not re-announce old work.
 */
class NotificationCenter(
    private val context: Context,
    private val client: MimoClient,
    private val database: MimoDatabase,
    /**
     * Owned by the container. It is passed in rather than reached for through `MimoApp.container`,
     * which is still unassigned while the container itself is being built — that reach caused a
     * first-launch crash (`UninitializedPropertyAccessException`) before the window ever opened.
     */
    private val scope: CoroutineScope
) {
    private val manager = NotificationManagerCompat.from(context)

    fun ensureChannels() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channels = listOf(
            NotificationChannel(
                CHANNEL_TASKS, "Task finished", NotificationManager.IMPORTANCE_DEFAULT
            ).apply { description = "A goal MIMO was working on has finished." },
            NotificationChannel(
                CHANNEL_APPROVALS, "Waiting for you", NotificationManager.IMPORTANCE_HIGH
            ).apply { description = "MIMO paused because it needs your approval." },
            NotificationChannel(
                CHANNEL_ACTIVITY, "Agent activity", NotificationManager.IMPORTANCE_LOW
            ).apply { description = "What the specialists are doing in the background." }
        )
        channels.forEach { manager.createNotificationChannel(it) }
    }

    fun start(isPaired: () -> Boolean, settingsProvider: () -> AppSettings) {
        ensureChannels()
        scope.launch {
            // A short warm-up delay: the first screen should not pay for a network round trip.
            delay(4_000)
            while (isActive) {
                if (isPaired() && canPost()) {
                    runCatching { poll(settingsProvider()) }
                }
                // 60 s, not 20: a phone that is not looking at MIMO should not wake its radio every
                // twenty seconds all day (that was 4,320 requests a day for an idle app). The
                // Activity screen polls at 5 s while it is actually open.
                delay(POLL_INTERVAL_MS)
            }
        }
    }

    private fun canPost(): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            ContextCompat.checkSelfPermission(
                context, Manifest.permission.POST_NOTIFICATIONS
            ) == PackageManager.PERMISSION_GRANTED

    private suspend fun poll(settings: AppSettings) {
        val tasks = try {
            client.get("/agent/tasks?limit=20", com.mimo.companion.data.remote.TasksResponse.serializer()).tasks
        } catch (e: ApiException) {
            return
        }
        val dao = database.notifiedTasks()
        for (task in tasks) {
            val seen = dao.byId(task.id)
            if (task.needsApproval && seen?.status != "approval") {
                if (settings.notifyApprovals) postApproval(task)
                dao.upsert(NotifiedTaskEntity(task.id, "approval", Instant.now().toString()))
                continue
            }
            val terminal = task.status in TERMINAL
            if (terminal && seen?.status != task.status) {
                if (settings.notifyTasks) postFinished(task)
                dao.upsert(NotifiedTaskEntity(task.id, task.status, Instant.now().toString()))
            }
        }
        dao.pruneBefore(Instant.now().minus(7, ChronoUnit.DAYS).toString())
    }

    private fun postFinished(task: AgentTaskDto) {
        val ok = task.status == "succeeded"
        val title = if (ok) "MIMO finished a task" else "A MIMO task ${task.status.replace('_', ' ')}"
        val body = task.goal.ifBlank { task.agent ?: "Task ${task.id.take(8)}" }
        notify(CHANNEL_TASKS, task.id.hashCode(), title, body, task.id)
    }

    private fun postApproval(task: AgentTaskDto) {
        val body = task.goal.ifBlank { "MIMO needs your approval before it continues." }
        notify(CHANNEL_APPROVALS, task.id.hashCode() + 1, "MIMO is waiting for you", body, task.id)
    }

    private fun notify(channel: String, id: Int, title: String, body: String, taskId: String) {
        if (!canPost()) return
        val intent = Intent(context, MainActivity::class.java).apply {
            putExtra(MainActivity.EXTRA_TASK_ID, taskId)
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val pending = PendingIntent.getActivity(
            context, id, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val notification = NotificationCompat.Builder(context, channel)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(pending)
            .setAutoCancel(true)
            .build()
        runCatching { manager.notify(id, notification) }
    }

    companion object {
        const val POLL_INTERVAL_MS = 60_000L
        const val CHANNEL_TASKS = "mimo_tasks"
        const val CHANNEL_APPROVALS = "mimo_approvals"
        const val CHANNEL_ACTIVITY = "mimo_activity"

        val TERMINAL = setOf("succeeded", "failed", "cancelled", "timed_out")
    }
}
