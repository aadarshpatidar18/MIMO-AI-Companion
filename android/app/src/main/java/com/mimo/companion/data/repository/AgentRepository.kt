package com.mimo.companion.data.repository

import com.mimo.companion.data.remote.AgentTaskDto
import com.mimo.companion.data.remote.MimoClient
import com.mimo.companion.data.remote.MimoJson
import com.mimo.companion.data.remote.TaskStartBody
import com.mimo.companion.data.remote.TaskStarted
import com.mimo.companion.data.remote.TasksResponse
import kotlinx.serialization.Serializable

@Serializable
private data class ConfirmBody(val approve: Boolean)

/**
 * What MIMO is doing, and the two things the phone is allowed to do about it: start a goal, stop a
 * task, or answer a confirmation. Nothing here can raise the autonomy level — that stays on the PC.
 */
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

    suspend fun cancel(id: String) {
        client.post("/agent/tasks/$id/cancel", null, kotlinx.serialization.json.JsonElement.serializer())
    }

    /** True when the task was waiting for a decision; a false answer is the user saying no. */
    suspend fun confirm(id: String, approve: Boolean) {
        val body = MimoJson.encodeToString(ConfirmBody.serializer(), ConfirmBody(approve))
        client.post("/agent/tasks/$id/confirm", body, kotlinx.serialization.json.JsonElement.serializer())
    }
}
