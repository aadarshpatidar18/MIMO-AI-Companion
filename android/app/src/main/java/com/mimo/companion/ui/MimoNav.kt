package com.mimo.companion.ui

import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Chat
import androidx.compose.material.icons.filled.Memory
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Smartphone
import androidx.compose.material.icons.filled.Timeline
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.mimo.companion.ui.screens.ActivityScreen
import com.mimo.companion.ui.screens.ChatScreen
import com.mimo.companion.ui.screens.MemoryScreen
import com.mimo.companion.ui.screens.OperatorScreen
import com.mimo.companion.ui.screens.SettingsScreen
import com.mimo.companion.viewmodel.ActivityViewModel
import com.mimo.companion.viewmodel.ChatViewModel
import com.mimo.companion.viewmodel.MemoryViewModel
import com.mimo.companion.viewmodel.OperatorViewModel
import com.mimo.companion.viewmodel.SettingsViewModel

private data class Tab(
    val route: String,
    val label: String,
    val icon: androidx.compose.ui.graphics.vector.ImageVector
)

private val tabs = listOf(
    Tab("chat", "Chat", Icons.Filled.Chat),
    Tab("memory", "Memory", Icons.Filled.Memory),
    Tab("activity", "Activity", Icons.Filled.Timeline),
    Tab("operator", "Operator", Icons.Filled.Smartphone),
    Tab("settings", "Settings", Icons.Filled.Settings)
)

@Composable
fun MimoApp(
    onOpenAccessibility: () -> Unit,
    onRequestScreenCapture: () -> Unit,
    onRequestNotifications: () -> Unit
) {
    val navController = rememberNavController()
    val backStack by navController.currentBackStackEntryAsState()
    val currentDestination = backStack?.destination

    Scaffold(
        bottomBar = {
            NavigationBar {
                tabs.forEach { tab ->
                    val selected = currentDestination?.hierarchy?.any { it.route == tab.route } == true
                    NavigationBarItem(
                        selected = selected,
                        onClick = {
                            navController.navigate(tab.route) {
                                popUpTo(navController.graph.findStartDestination().id) {
                                    saveState = true
                                }
                                launchSingleTop = true
                                restoreState = true
                            }
                        },
                        icon = { Icon(tab.icon, contentDescription = tab.label) },
                        label = { Text(tab.label) }
                    )
                }
            }
        }
    ) { padding ->
        NavHost(
            navController = navController,
            startDestination = "chat",
            modifier = Modifier.padding(padding)
        ) {
            composable("chat") {
                val viewModel: ChatViewModel = viewModel()
                ChatScreen(viewModel)
            }
            composable("memory") {
                val viewModel: MemoryViewModel = viewModel()
                MemoryScreen(viewModel)
            }
            composable("activity") {
                val viewModel: ActivityViewModel = viewModel()
                ActivityScreen(viewModel)
            }
            composable("operator") {
                val viewModel: OperatorViewModel = viewModel()
                OperatorScreen(viewModel)
            }
            composable("settings") {
                val viewModel: SettingsViewModel = viewModel()
                SettingsScreen(
                    viewModel = viewModel,
                    onOpenAccessibility = onOpenAccessibility,
                    onRequestScreenCapture = onRequestScreenCapture,
                    onRequestNotifications = onRequestNotifications
                )
            }
        }
    }
}
