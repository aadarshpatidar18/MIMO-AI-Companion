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
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.mimo.companion.ui.components.EmptyState
import com.mimo.companion.viewmodel.MemoryViewModel

@Composable
fun MemoryScreen(viewModel: MemoryViewModel, modifier: Modifier = Modifier) {
    var adding by remember { mutableStateOf(false) }
    var editing by remember { mutableStateOf<Int?>(null) }

    Column(modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            OutlinedTextField(
                value = viewModel.query,
                onValueChange = viewModel::onQuery,
                modifier = Modifier.weight(1f),
                placeholder = { Text("Search what MIMO remembers") },
                singleLine = true,
                leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null) }
            )
            IconButton(onClick = { viewModel.refresh() }) { Text("Go") }
            IconButton(onClick = { adding = true }) {
                Icon(Icons.Filled.Add, contentDescription = "Add a fact")
            }
        }

        if (viewModel.loading) LinearProgressIndicator(Modifier.fillMaxWidth())

        viewModel.notice?.let {
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(it, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                TextButton(onClick = viewModel::dismiss) { Text("Dismiss") }
            }
        }

        if (viewModel.memories.isEmpty() && !viewModel.loading) {
            EmptyState(
                "Nothing remembered yet",
                "Facts MIMO keeps — preferences, projects, people — appear here. " +
                    "It also writes here by itself when you tell it something worth keeping."
            )
        } else {
            LazyColumn(
                Modifier.fillMaxSize(),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                items(viewModel.memories, key = { it.id }) { memory ->
                    Card(
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.surfaceVariant
                        ),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Column(Modifier.padding(12.dp)) {
                            Text(memory.content, style = MaterialTheme.typography.bodyMedium)
                            Spacer(Modifier.size(6.dp))
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(
                                    "${memory.category} · importance ${memory.importance} · recalled ${memory.accessCount}×",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                                Spacer(Modifier.weight(1f))
                                TextButton(onClick = { editing = memory.id }) { Text("Correct") }
                                IconButton(onClick = { viewModel.forget(memory.content) }) {
                                    Icon(Icons.Filled.Delete, contentDescription = "Forget", modifier = Modifier.size(18.dp))
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    if (adding) {
        var text by remember { mutableStateOf("") }
        var category by remember { mutableStateOf("preference") }
        AlertDialog(
            onDismissRequest = { adding = false },
            title = { Text("Remember this") },
            text = {
                Column {
                    OutlinedTextField(
                        value = text,
                        onValueChange = { text = it },
                        label = { Text("What should MIMO remember?") },
                        modifier = Modifier.fillMaxWidth()
                    )
                    Spacer(Modifier.size(8.dp))
                    OutlinedTextField(
                        value = category,
                        onValueChange = { category = it },
                        label = { Text("Category") },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true
                    )
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    viewModel.remember(text, category)
                    adding = false
                }) { Text("Save") }
            },
            dismissButton = { TextButton(onClick = { adding = false }) { Text("Cancel") } }
        )
    }

    editing?.let { id ->
        val memory = viewModel.memories.firstOrNull { it.id == id }
        var text by remember(id) { mutableStateOf(memory?.content.orEmpty()) }
        var importance by remember(id) { mutableStateOf((memory?.importance ?: 3).toFloat()) }
        AlertDialog(
            onDismissRequest = { editing = null },
            title = { Text("Correct this memory") },
            text = {
                Column {
                    OutlinedTextField(
                        value = text,
                        onValueChange = { text = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("Wording") }
                    )
                    Spacer(Modifier.size(12.dp))
                    Text("Importance ${importance.toInt()}", style = MaterialTheme.typography.labelMedium)
                    Slider(
                        value = importance,
                        onValueChange = { importance = it },
                        valueRange = 1f..5f,
                        steps = 3
                    )
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    viewModel.correct(id, text, importance.toInt())
                    editing = null
                }) { Text("Save") }
            },
            dismissButton = { TextButton(onClick = { editing = null }) { Text("Cancel") } }
        )
    }
}
