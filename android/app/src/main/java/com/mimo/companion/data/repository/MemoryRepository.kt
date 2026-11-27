package com.mimo.companion.data.repository

import com.mimo.companion.data.remote.MemoryBody
import com.mimo.companion.data.remote.MemoryDto
import com.mimo.companion.data.remote.MemoryPatchBody
import com.mimo.companion.data.remote.MemoryResponse
import com.mimo.companion.data.remote.MimoClient
import com.mimo.companion.data.remote.MimoJson

/**
 * The memory dashboard reads the same store MIMO itself reasons over — not a copy. That is why this
 * repository has no cache: a fact corrected on the phone must be the fact the laptop uses on the
 * next turn, so every screen shows what the backend just said.
 */
class MemoryRepository(private val client: MimoClient) {

    suspend fun search(keyword: String = "", category: String? = null): List<MemoryDto> {
        val query = buildString {
            append("/memory?keyword=").append(java.net.URLEncoder.encode(keyword, "UTF-8"))
            if (!category.isNullOrBlank()) append("&category=").append(category)
        }
        return client.get(query, MemoryResponse.serializer()).memories
    }

    suspend fun remember(content: String, category: String?) {
        val body = MimoJson.encodeToString(
            MemoryBody.serializer(),
            MemoryBody(content = content.trim(), category = category)
        )
        client.post("/memory", body, MemoryResponse.serializer())
    }

    suspend fun correct(id: Int, content: String? = null, category: String? = null, importance: Int? = null) {
        val body = MimoJson.encodeToString(
            MemoryPatchBody.serializer(),
            MemoryPatchBody(content = content, category = category, importance = importance)
        )
        client.put("/memory/$id", body, MemoryResponse.serializer())
    }

    suspend fun forget(keyword: String) {
        val body = MimoJson.encodeToString(
            com.mimo.companion.data.remote.ForgetBody.serializer(),
            com.mimo.companion.data.remote.ForgetBody(keyword.trim())
        )
        client.delete("/memory", body)
    }
}
