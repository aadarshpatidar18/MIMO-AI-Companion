package com.mimo.companion.wire

import com.mimo.companion.data.remote.AgentTaskDto
import com.mimo.companion.data.remote.ChatResponse
import com.mimo.companion.data.remote.ConversationDto
import com.mimo.companion.data.remote.ConversationsResponse
import com.mimo.companion.data.remote.DeviceDto
import com.mimo.companion.data.remote.DevicesResponse
import com.mimo.companion.data.remote.MemoryResponse
import com.mimo.companion.data.remote.MessagesResponse
import com.mimo.companion.data.remote.MimoJson
import com.mimo.companion.data.remote.TasksResponse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Decodes real backend responses with the app's own wire types.
 *
 * The fixtures in `src/test/resources/wire` were captured from a running backend, not written by
 * hand: a hand-written sample only tests the author's belief about the format. This is the test
 * that catches a field whose JSON type changed — which is exactly how a `created_at` that is an
 * epoch number, not a string, would have broken every screen at runtime while the unit tests
 * stayed green.
 */
class WireContractTest {

    private fun fixture(name: String): String =
        javaClass.classLoader!!.getResourceAsStream("wire/$name.json")!!
            .bufferedReader().use { it.readText() }

    @Test
    fun `the chat response decodes and its ids survive`() {
        val body = MimoJson.decodeFromString(ChatResponse.serializer(), fixture("chat"))
        assertTrue(body.success)
        assertTrue(body.response.isNotBlank())
        assertNotNull(body.userMessageId)
        assertNotNull(body.assistantMessageId)
        assertTrue(body.assistantMessageId!! > body.userMessageId!!)
        assertNotNull("created_at is an epoch number on the wire", body.createdAt)
    }

    @Test
    fun `the conversation list decodes`() {
        val body = MimoJson.decodeFromString(ConversationsResponse.serializer(),
            fixture("conversations"))
        assertEquals(1, body.count)
        val conversation: ConversationDto = body.conversations.first()
        assertTrue(conversation.id.isNotBlank())
        assertNotNull(conversation.createdAt)
    }

    @Test
    fun `messages decode in order with timestamps`() {
        val body = MimoJson.decodeFromString(MessagesResponse.serializer(), fixture("messages"))
        assertEquals(2, body.count)
        assertEquals(listOf("user", "assistant"), body.messages.map { it.role })
        assertTrue(body.messages.all { it.createdAt != null })
        assertTrue(body.nextAfterId > 0)
    }

    @Test
    fun `memory rows decode`() {
        val body = MimoJson.decodeFromString(MemoryResponse.serializer(), fixture("memory"))
        assertTrue(body.memories.isNotEmpty())
        assertTrue(body.memories.first().content.isNotBlank())
    }

    @Test
    fun `a finished task decodes, including its agent and error shape`() {
        val task = MimoJson.decodeFromString(AgentTaskDto.serializer(), fixture("task"))
        assertTrue(task.id.isNotBlank())
        assertTrue(task.status.isNotBlank())
        assertEquals("general", task.agent)
        assertNotNull(task.createdAt)
    }

    @Test
    fun `the task list decodes`() {
        val body = MimoJson.decodeFromString(TasksResponse.serializer(), fixture("tasks"))
        assertTrue(body.tasks.isNotEmpty())
        assertTrue(body.tasks.all { it.id.isNotBlank() })
    }

    @Test
    fun `devices decode with their scopes`() {
        val body = MimoJson.decodeFromString(DevicesResponse.serializer(), fixture("devices"))
        assertTrue(body.devices.isNotEmpty())
        val device: DeviceDto = body.devices.first()
        assertTrue(device.scopes.isNotEmpty())
        assertNotNull(device.lastSeen)
    }

    @Test
    fun `a device row decodes on its own`() {
        val device = MimoJson.decodeFromString(DeviceDto.serializer(), fixture("me"))
        assertTrue(device.id.isNotBlank())
        assertTrue(device.kind.isNotBlank())
    }
}
