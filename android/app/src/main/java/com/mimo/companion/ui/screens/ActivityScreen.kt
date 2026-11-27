package com.mimo.companion.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.mimo.companion.data.remote.AgentTaskDto
import com.mimo.companion.ui.components.EmptyState
import com.mimo.companion.viewmodel.ActivityViewModel

@Composable
fun ActivityScreen(viewModel: ActivityViewModel, modifier: Modifier = Modifier) {
    Column(modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text("Agent activity", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            if (viewModel.loading) {
                CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
            }
            IconButton(onClick = viewModel::refresh) {
                Icon(Icons.Filled.Refresh, contentDescription = "Refresh")
            }
        }

        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = viewModel.newGoal,
                onValueChange = viewModel::onGoal,
                modifier = Modifier.weight(1f),
                placeholder = { Text("Give MIMO a goal") },
                singleLine = true
            )
            Spacer(Modifier.size(8.dp))
            OutlinedButton(onClick = viewModel::start) { Text("Start") }
        }

        viewModel.notice?.let {
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(it, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                TextButton(onClick = viewModel::dismiss) { Text("Dismiss") }
            }
        }

        if (viewModel.tasks.isEmpty()) {
            EmptyState(
                "Nothing running",
                "Every goal MIMO works on appears here with its specialist, its steps and a Stop button."
            )
        } else {
            LazyColumn(
                Modifier.fillMaxSize(),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                items(viewModel.tasks, key = { it.id }) { task -> TaskCard(task, viewModel) }
            }
        }
    }
}

@Composable
private fun TaskCard(task: AgentTaskDto, viewModel: ActivityViewModel) {
    val running = task.status in setOf("queued", "running", "planning")
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                AssistChip(
                    onClick = {},
                    label = { Text(task.status.replace('_', ' ')) }
                )
                Spacer(Modifier.size(8.dp))
                Text(
                    task.agentKey ?: task.agent ?: "generalist",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            Spacer(Modifier.size(6.dp))
            Text(task.goal, style = MaterialTheme.typography.bodyMedium)
            Spacer(Modifier.size(6.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    task.createdAt?.let { formatTime(it) }.orEmpty(),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Spacer(Modifier.weight(1f))
                if (task.needsApproval) {
                    TextButton(onClick = { viewModel.confirm(task.id, true) }) { Text("Approve") }
                    TextButton(onClick = { viewModel.confirm(task.id, false) }) { Text("Deny") }
                } else if (running) {
                    TextButton(onClick = { viewModel.cancel(task.id) }) {
                        Text("Stop", color = Color(0xFFB3261E))
                    }
                }
            }
        }
    }
}
