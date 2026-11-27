package com.mimo.companion.data.repository

import com.mimo.companion.data.remote.AgentTaskDto
import com.mimo.companion.data.remote.MimoClient
import com.mimo.companion.data.remote.MimoJson
import com.mimo.companion.data.remote.TaskStartBody
import com.mimo.companion.data.remote.TaskStarted
import com.mimo.companion.data.remote.TasksResponse
import kotlinx.serialization.Serializable

@Serializable
private data class ConfirmBody(val approve: Boolean, val step_index: Int? = null)

/**
 * What MIMO is doing, and the two things the phone is allowed to do about it: start a goal, stop a
 * task, or answer a confirmation. Nothing here can raise the autonomy level — that stays on the PC.
 */
private val RUNNING_STATES = setOf("queued", "running", "planning")

class AgentRepository(private val client: MimoClient) {

    suspend fun tasks(limit: Int = 50): List<AgentTaskDto> =
        client.get("/agent/tasks?limit=$limit", TasksResponse.serializer()).tasks

    suspend fun task(id: String): AgentTaskDto =
        client.get("/agent/tasks/$id", AgentTaskDto.serializer())

    suspend fun start(goal: String, agent: String? = null): TaskStarted {
        val body = MimoJson.encodeToString(
            TaskStartBody.serializer(),
            TaskStartBody(goal = goal.trim(), agent = agent)
        )
        return client.post("/agent/tasks", body, TaskStarted.serializer())
    }

    /**
     * Emergency stop: cancel every task still queued, planning or running.
     *
     * Returns the ids that were asked to stop. Failures are counted rather than thrown: if the
     * fourth cancellation fails, the first three did not happen for nothing, and the caller needs
     * to know that one task may keep running.
     */
    suspend fun stopAll(): Pair<Int, Int> {
        var stopped = 0
        var failed = 0
        for (task in tasks(limit = 100)) {
            if (task.status in RUNNING_STATES) {
                val ok = runCatching { cancel(task.id) }.isSuccess
                if (ok) stopped++ else failed++
            }
        }
        return stopped to failed
    }

    suspend fun cancel(id: String) {
        client.post("/agent/tasks/$id/cancel", null, kotlinx.serialization.json.JsonElement.serializer())
    }

    /**
     * Answer a paused step. [stepIndex] names the step the user was looking at, so a late tap
     * cannot approve the step that happens to be waiting afterwards.
     */
    suspend fun confirm(id: String, approve: Boolean, stepIndex: Int? = null) {
        val body = MimoJson.encodeToString(
            ConfirmBody.serializer(), ConfirmBody(approve, stepIndex)
        )
        client.post("/agent/tasks/$id/confirm", body, kotlinx.serialization.json.JsonElement.serializer())
    }
}
