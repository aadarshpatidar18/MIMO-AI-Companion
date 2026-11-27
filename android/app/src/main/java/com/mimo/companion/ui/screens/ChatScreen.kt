package com.mimo.companion.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.SwapHoriz
import androidx.compose.material3.AssistChip
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mimo.companion.data.local.MessageEntity
import com.mimo.companion.data.local.MessageStatus
import com.mimo.companion.device.LinkState
import com.mimo.companion.ui.components.EmptyState
import com.mimo.companion.ui.components.StatusPill
import com.mimo.companion.viewmodel.ChatViewModel
import com.mimo.companion.voice.VoiceState
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(viewModel: ChatViewModel, modifier: Modifier = Modifier) {
    val messages by viewModel.messages.collectAsStateWithLifecycle()
    val conversations by viewModel.conversations.collectAsStateWithLifecycle()
    val connection by viewModel.connection.collectAsStateWithLifecycle()
    val active by viewModel.active.collectAsStateWithLifecycle()
    val voice by viewModel.voiceState.collectAsStateWithLifecycle()

    val listState = rememberLazyListState()
    var showConversations by remember { mutableStateOf(false) }

    LaunchedEffect(messages.size) {
        if (messages.isNotEmpty()) listState.animateScrollToItem(messages.lastIndex)
    }

    Column(modifier.fillMaxSize().imePadding()) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            StatusPill(connection)
            Spacer(Modifier.weight(1f))
            Text(
                conversations.firstOrNull { it.id == active }?.title?.take(28) ?: "New chat",
                style = MaterialTheme.typography.labelLarge
            )
            IconButton(onClick = { showConversations = true }) {
                Icon(Icons.Filled.SwapHoriz, contentDescription = "Conversations")
            }
            IconButton(onClick = { viewModel.newConversation() }) {
                Icon(Icons.Filled.Add, contentDescription = "New conversation")
            }
        }
        HorizontalDivider()

        viewModel.notice?.let { notice ->
            Surface(color = MaterialTheme.colorScheme.secondaryContainer) {
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(notice, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                    TextButton(onClick = { viewModel.dismissNotice() }) { Text("Dismiss") }
                }
            }
        }

        if (connection.state == LinkState.OFFLINE) {
            Surface(color = MaterialTheme.colorScheme.tertiaryContainer) {
                Text(
                    "MIMO is unreachable. You can read this conversation and type; messages send when it reconnects.",
                    style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.fillMaxWidth().padding(12.dp)
                )
            }
        }

        Box(Modifier.weight(1f)) {
            if (messages.isEmpty()) {
                EmptyState(
                    "Talk to MIMO",
                    "Ask a question, give it a task, or hold the microphone and speak. " +
                        "Your conversation is shared with your other paired devices."
                )
            } else {
                LazyColumn(
                    state = listState,
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    items(messages, key = { it.localId }) { message -> MessageBubble(message) }
                }
            }
        }

        if (voice is VoiceState.Heard) {
            Text(
                (voice as VoiceState.Heard).partial,
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 4.dp)
            )
        }

        Row(
            Modifier.fillMaxWidth().padding(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            OutlinedTextField(
                value = viewModel.input,
                onValueChange = viewModel::onInput,
                modifier = Modifier.weight(1f),
                placeholder = { Text("Message MIMO…") },
                maxLines = 4,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(onSend = { viewModel.send() })
            )
            Spacer(Modifier.size(8.dp))
            IconButton(
                onClick = {
                    if (voice is VoiceState.Listening) viewModel.stopVoice() else viewModel.startVoice()
                },
                colors = IconButtonDefaults.iconButtonColors(
                    containerColor = if (voice is VoiceState.Listening)
                        MaterialTheme.colorScheme.errorContainer
                    else MaterialTheme.colorScheme.surfaceVariant
                )
            ) {
                Icon(
                    if (voice is VoiceState.Listening) Icons.Filled.Stop else Icons.Filled.Mic,
                    contentDescription = "Voice"
                )
            }
            Spacer(Modifier.size(6.dp))
            FilledIconButton(
                onClick = { viewModel.send() },
                enabled = viewModel.input.isNotBlank() && !viewModel.sending
            ) {
                Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "Send")
            }
        }
    }

    if (showConversations) {
        androidx.compose.material3.AlertDialog(
            onDismissRequest = { showConversations = false },
            confirmButton = {
                TextButton(onClick = { showConversations = false }) { Text("Close") }
            },
            title = { Text("Conversations") },
            text = {
                Column {
                    if (conversations.isEmpty()) {
                        Text("No conversations yet.")
                    }
                    conversations.take(12).forEach { conversation ->
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            AssistChip(
                                onClick = {
                                    viewModel.open(conversation.id)
                                    showConversations = false
                                },
                                label = {
                                    Text(
                                        (conversation.title.ifBlank { "Conversation" }).take(30),
                                        style = MaterialTheme.typography.bodySmall
                                    )
                                }
                            )
                            Spacer(Modifier.weight(1f))
                            IconButton(onClick = { viewModel.delete(conversation.id) }) {
                                Icon(Icons.Filled.Delete, contentDescription = "Delete", modifier = Modifier.size(18.dp))
                            }
                        }
                    }
                }
            }
        )
    }
}

@Composable
private fun MessageBubble(message: MessageEntity) {
    val fromUser = message.role == "user"
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = if (fromUser) Arrangement.End else Arrangement.Start
    ) {
        Surface(
            color = if (fromUser) MaterialTheme.colorScheme.primaryContainer
            else MaterialTheme.colorScheme.surfaceVariant,
            shape = RoundedCornerShape(
                topStart = 16.dp, topEnd = 16.dp,
                bottomStart = if (fromUser) 16.dp else 4.dp,
                bottomEnd = if (fromUser) 4.dp else 16.dp
            ),
            modifier = Modifier.fillMaxWidth(0.86f)
        ) {
            Column(Modifier.padding(12.dp)) {
                Text(message.content, style = MaterialTheme.typography.bodyMedium)
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                    if (message.status == MessageStatus.PENDING.name) {
                        Text("queued · ", style = MaterialTheme.typography.labelSmall)
                    }
                    if (message.status == MessageStatus.FAILED.name) {
                        Text("not sent · ", style = MaterialTheme.typography.labelSmall)
                    }
                    Text(
                        formatTime(message.createdAt),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }
    }
}

private val timeFormatter: DateTimeFormatter = DateTimeFormatter.ofPattern("HH:mm")

internal fun formatTime(iso: String): String = runCatching {
    Instant.parse(iso).atZone(ZoneId.systemDefault()).format(timeFormatter)
}.getOrDefault("")
