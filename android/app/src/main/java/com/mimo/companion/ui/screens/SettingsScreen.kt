package com.mimo.companion.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mimo.companion.ui.components.SectionCard
import com.mimo.companion.ui.components.StatusPill
import com.mimo.companion.viewmodel.SettingsViewModel

@Composable
fun SettingsScreen(
    viewModel: SettingsViewModel,
    onOpenAccessibility: () -> Unit,
    onRequestScreenCapture: () -> Unit,
    onRequestNotifications: () -> Unit,
    modifier: Modifier = Modifier
) {
    val settings by viewModel.settings.collectAsStateWithLifecycle()
    val connection by viewModel.connection.collectAsStateWithLifecycle()

    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {

        SectionCard("Connection") {
            StatusPill(connection)
            Spacer(Modifier.size(8.dp))
            OutlinedTextField(
                value = viewModel.url,
                onValueChange = viewModel::onUrl,
                label = { Text("MIMO address") },
                placeholder = { Text("http://192.168.0.151:8000") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true
            )
            Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                OutlinedButton(onClick = viewModel::saveUrl) { Text("Save address") }
                Spacer(Modifier.weight(1f))
                Text(
                    if (settings.isPaired) "Paired" else "Not paired",
                    style = MaterialTheme.typography.labelMedium
                )
            }
        }

        if (!settings.isPaired) {
            SectionCard("Pair this phone") {
                Text(
                    "On your PC run `python -m backend.main pair`, then type the code it prints.",
                    style = MaterialTheme.typography.bodySmall
                )
                Spacer(Modifier.size(8.dp))
                OutlinedTextField(
                    value = viewModel.code,
                    onValueChange = viewModel::onCode,
                    label = { Text("Pairing code") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true
                )
                Spacer(Modifier.size(8.dp))
                OutlinedTextField(
                    value = viewModel.deviceName,
                    onValueChange = viewModel::onDeviceName,
                    label = { Text("Name this phone") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true
                )
                Spacer(Modifier.size(10.dp))
                Button(
                    onClick = viewModel::pair,
                    enabled = !viewModel.pairing,
                    modifier = Modifier.fillMaxWidth()
                ) { Text(if (viewModel.pairing) "Pairing…" else "Pair") }
            }
        } else {
            SectionCard("This device") {
                Text(viewModel.deviceName.ifBlank { "Android phone" }, style = MaterialTheme.typography.bodyMedium)
                if (viewModel.deviceScopes.isNotEmpty()) {
                    Text(
                        "Scopes: " + viewModel.deviceScopes.joinToString(", "),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                Spacer(Modifier.size(8.dp))
                Row {
                    OutlinedButton(onClick = viewModel::rotateToken) { Text("New token") }
                    Spacer(Modifier.size(8.dp))
                    OutlinedButton(onClick = viewModel::unpair) { Text("Unpair") }
                }
            }
        }

        SectionCard("Notifications") {
            ToggleRow("Task finished", settings.notifyTasks, viewModel::setNotifyTasks)
            ToggleRow("Waiting for my approval", settings.notifyApprovals, viewModel::setNotifyApprovals)
            ToggleRow("Agent activity", settings.notifyActivity, viewModel::setNotifyActivity)
            TextButton(onClick = onRequestNotifications) { Text("Allow notifications in Android") }
        }

        SectionCard("Voice") {
            ToggleRow("Speak MIMO's answers aloud", settings.voiceReplies, viewModel::setVoiceReplies)
            Text(
                "Speech uses this phone's own engines. The heavier local Whisper/Kokoro models run on your PC.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }

        SectionCard("Permissions the operator needs") {
            Text(
                "MIMO can only see and touch the screen while you have granted these, and you can " +
                    "take them back at any time in Android settings.",
                style = MaterialTheme.typography.bodySmall
            )
            Spacer(Modifier.size(8.dp))
            OutlinedButton(onClick = onOpenAccessibility) { Text("Accessibility service") }
            Spacer(Modifier.size(6.dp))
            OutlinedButton(onClick = onRequestScreenCapture) { Text("Screen capture") }
        }

        SectionCard("About") {
            Text("MIMO Companion ${viewModel.version}", style = MaterialTheme.typography.bodySmall)
            HorizontalDivider(Modifier.padding(vertical = 8.dp))
            Text(
                "Everything is sent to your own MIMO backend. This app has no analytics and no third-party servers.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }

        viewModel.notice?.let {
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(it, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                TextButton(onClick = viewModel::dismiss) { Text("OK") }
            }
        }
    }
}

@Composable
private fun ToggleRow(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
        Switch(checked = checked, onCheckedChange = onChange)
    }
}
