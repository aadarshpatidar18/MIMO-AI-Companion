package com.mimo.companion.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mimo.companion.viewmodel.OperatorViewModel

@Composable
fun OperatorScreen(viewModel: OperatorViewModel, modifier: Modifier = Modifier) {
    val status by viewModel.status.collectAsStateWithLifecycle()

    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Screen operator", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            IconButton(onClick = { viewModel.readScreen() }) {
                Icon(Icons.Filled.Refresh, contentDescription = "Read screen")
            }
        }
        Text(
            if (status.connected) {
                "Reading ${status.packageName.ifBlank { "the screen" }} — ${status.elementCount} elements"
            } else {
                "Off. Turn on MIMO in Settings → Accessibility to let it read and operate this phone."
            },
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Spacer(Modifier.size(10.dp))

        if (viewModel.busy) LinearProgressIndicator(Modifier.fillMaxWidth())

        Button(onClick = { viewModel.readScreen() }, modifier = Modifier.fillMaxWidth()) {
            Text("Read and understand this screen")
        }

        viewModel.notice?.let {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(it, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                TextButton(onClick = viewModel::dismiss) { Text("OK") }
            }
        }

        val analysis = viewModel.analysis
        if (analysis != null) {
            Spacer(Modifier.size(10.dp))
            Card(
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(Modifier.padding(12.dp)) {
                    Text("What is on screen", style = MaterialTheme.typography.titleSmall)
                    Spacer(Modifier.size(6.dp))
                    Text(
                        analysis.summary(),
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.heightIn(max = 260.dp).verticalScroll(rememberScrollState())
                    )
                }
            }

            Spacer(Modifier.size(14.dp))
            Text("Operate", style = MaterialTheme.typography.titleSmall)
            Spacer(Modifier.size(6.dp))
            OutlinedTextField(
                value = viewModel.target,
                onValueChange = viewModel::onTarget,
                label = { Text("Element name (e.g. “Search”, “Send”)") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true
            )
            Spacer(Modifier.size(8.dp))
            Row(Modifier.fillMaxWidth()) {
                Button(onClick = { viewModel.tap() }, modifier = Modifier.weight(1f)) { Text("Tap it") }
                Spacer(Modifier.size(8.dp))
                Button(onClick = { viewModel.scroll(true) }, modifier = Modifier.weight(1f)) {
                    Icon(Icons.Filled.KeyboardArrowDown, contentDescription = null)
                    Text("Scroll")
                }
            }
            Spacer(Modifier.size(8.dp))
            OutlinedTextField(
                value = viewModel.text,
                onValueChange = viewModel::onText,
                label = { Text("Text to type into that field") },
                modifier = Modifier.fillMaxWidth(),
                maxLines = 3
            )
            Spacer(Modifier.size(8.dp))
            Row(Modifier.fillMaxWidth()) {
                Button(onClick = { viewModel.type() }, modifier = Modifier.weight(1f)) { Text("Type") }
                Spacer(Modifier.size(8.dp))
                Button(onClick = { viewModel.back() }, modifier = Modifier.weight(1f)) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = null)
                    Text("Back")
                }
            }
        }

        Spacer(Modifier.size(16.dp))
        Text("Recent actions", style = MaterialTheme.typography.titleSmall)
        if (status.log.isEmpty()) {
            Text("Nothing yet.", style = MaterialTheme.typography.bodySmall)
        } else {
            status.log.forEach { line ->
                Text(line, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(vertical = 2.dp))
            }
        }
    }
}
