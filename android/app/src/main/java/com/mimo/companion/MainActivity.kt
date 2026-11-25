package com.mimo.companion

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.mimo.companion.ui.theme.MIMOTheme
import java.util.UUID
import java.util.concurrent.Executors

private val Background = Color(0xFF0D1117)
private val SurfaceColor = Color(0xFF161B22)
private val Accent = Color(0xFF7C9CFF)
private val PrimaryText = Color(0xFFF0F3F8)
private val SecondaryText = Color(0xFF929BAA)

data class ChatMessage(
    val text: String,
    val isUser: Boolean
)

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        setContent {
            MIMOTheme {
                MimoChatScreen()
            }
        }
    }
}

@Composable
fun MimoChatScreen() {

    var input by remember { mutableStateOf("") }
    var isLoading by remember { mutableStateOf(false) }
    var isConnected by remember { mutableStateOf(false) }

    val messages = remember {
        mutableStateListOf(
            ChatMessage(
                "Hello! I'm MIMO, your personal AI companion. What would you like to explore today?",
                false
            )
        )
    }

    val sessionId = remember {
        UUID.randomUUID().toString()
    }

    val listState = rememberLazyListState()
    val mainHandler = remember {
        Handler(Looper.getMainLooper())
    }

    val executor = remember {
        Executors.newSingleThreadExecutor()
    }

    DisposableEffect(Unit) {
        executor.execute {
            val connected = try {
                ApiService.checkConnection()
            } catch (error: Exception) {
                false
            }

            mainHandler.post {
                isConnected = connected
            }
        }

        onDispose {
            executor.shutdownNow()
        }
    }

    fun sendMessage() {

        val message = input.trim()

        if (message.isEmpty() || isLoading) return

        messages.add(ChatMessage(message, true))
        input = ""
        isLoading = true

        executor.execute {

            try {

                val response = ApiService.sendMessage(
                    message,
                    sessionId
                )

                mainHandler.post {
                    messages.add(
                        ChatMessage(response, false)
                    )

                    isLoading = false
                    isConnected = true
                }

            } catch (error: Exception) {

                mainHandler.post {
                    messages.add(
                        ChatMessage(
                            "I couldn't connect to my backend. Please check whether the MIMO server is running.",
                            false
                        )
                    )

                    isLoading = false
                    isConnected = false
                }
            }

            mainHandler.post {
                mainHandler.post {
                    if (messages.isNotEmpty()) {
                        messages.size
                    }
                }
            }
        }
    }

    Scaffold(
        containerColor = Background,
        modifier = Modifier.fillMaxSize(),
        bottomBar = {
            MessageInput(
                input = input,
                onInputChange = { input = it },
                onSend = { sendMessage() },
                isLoading = isLoading
            )
        }
    ) { padding ->

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
        ) {

            MimoHeader(isConnected)

            HorizontalDivider(
                color = Color(0xFF252D39)
            )

            LazyColumn(
                state = listState,
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
                contentPadding = PaddingValues(
                    horizontal = 18.dp,
                    vertical = 20.dp
                ),
                verticalArrangement = Arrangement.spacedBy(18.dp)
            ) {

                item {
                    Text(
                        text = "TODAY",
                        color = SecondaryText,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold
                    )
                }

                items(messages) { message ->
                    MessageBubble(message)
                }

                if (isLoading) {
                    item {
                        Text(
                            text = "MIMO is thinking...",
                            color = SecondaryText,
                            fontSize = 12.sp
                        )
                    }
                }
            }

            LaunchedEffect(messages.size, isLoading) {
                if (messages.isNotEmpty()) {
                    listState.animateScrollToItem(
                        if (isLoading) messages.size + 1 else messages.size
                    )
                }
            }
        }
    }
}

@Composable
fun MimoHeader(isConnected: Boolean) {

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(Background)
            .padding(horizontal = 20.dp, vertical = 18.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {

        Box(
            modifier = Modifier
                .size(48.dp)
                .background(
                    Accent.copy(alpha = 0.15f),
                    CircleShape
                )
                .border(
                    1.dp,
                    Accent.copy(alpha = 0.4f),
                    CircleShape
                ),
            contentAlignment = Alignment.Center
        ) {
            Text(
                text = "M",
                color = Accent,
                fontSize = 25.sp,
                fontWeight = FontWeight.Bold
            )
        }

        Spacer(modifier = Modifier.width(13.dp))

        Column(
            modifier = Modifier.weight(1f)
        ) {

            Text(
                text = "MIMO",
                color = PrimaryText,
                fontSize = 20.sp,
                fontWeight = FontWeight.Bold
            )

            Row(
                verticalAlignment = Alignment.CenterVertically
            ) {

                Box(
                    modifier = Modifier
                        .size(7.dp)
                        .background(
                            if (isConnected) Color(0xFF4ADE80)
                            else Color(0xFFF0B44D),
                            CircleShape
                        )
                )

                Spacer(modifier = Modifier.width(6.dp))

                Text(
                    text = if (isConnected) "Connected" else "Backend not connected",
                    color = SecondaryText,
                    fontSize = 11.sp
                )
            }
        }
    }
}

@Composable
fun MessageBubble(message: ChatMessage) {

    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (message.isUser) {
            Arrangement.End
        } else {
            Arrangement.Start
        },
        verticalAlignment = Alignment.Top
    ) {

        if (!message.isUser) {

            Box(
                modifier = Modifier
                    .size(30.dp)
                    .background(
                        Accent.copy(alpha = 0.15f),
                        CircleShape
                    ),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = "M",
                    color = Accent,
                    fontWeight = FontWeight.Bold
                )
            }

            Spacer(modifier = Modifier.width(9.dp))
        }

        Surface(
            color = if (message.isUser) {
                Color(0xFF263B68)
            } else {
                SurfaceColor
            },
            shape = RoundedCornerShape(17.dp),
            modifier = Modifier.widthIn(max = 290.dp)
        ) {

            Text(
                text = message.text,
                color = PrimaryText,
                fontSize = 14.sp,
                lineHeight = 21.sp,
                modifier = Modifier.padding(
                    horizontal = 15.dp,
                    vertical = 12.dp
                )
            )
        }
    }
}

@Composable
fun MessageInput(
    input: String,
    onInputChange: (String) -> Unit,
    onSend: () -> Unit,
    isLoading: Boolean
) {

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(Background)
            .navigationBarsPadding()
            .imePadding()
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {

        OutlinedTextField(
            value = input,
            onValueChange = onInputChange,
            modifier = Modifier.weight(1f),
            placeholder = {
                Text(
                    "Message MIMO...",
                    color = SecondaryText,
                    fontSize = 14.sp
                )
            },
            shape = RoundedCornerShape(25.dp),
            singleLine = true,
            keyboardOptions = KeyboardOptions(
                imeAction = ImeAction.Send
            ),
            keyboardActions = KeyboardActions(
                onSend = { onSend() }
            ),
            colors = OutlinedTextFieldDefaults.colors(
                focusedBorderColor = Accent,
                unfocusedBorderColor = Color(0xFF303846),
                focusedTextColor = PrimaryText,
                unfocusedTextColor = PrimaryText,
                cursorColor = Accent,
                focusedContainerColor = SurfaceColor,
                unfocusedContainerColor = SurfaceColor
            )
        )

        Spacer(modifier = Modifier.width(9.dp))

        Button(
            onClick = onSend,
            enabled = input.isNotBlank() && !isLoading,
            shape = CircleShape,
            colors = ButtonDefaults.buttonColors(
                containerColor = Accent,
                disabledContainerColor = Color(0xFF303846)
            ),
            contentPadding = PaddingValues(0.dp),
            modifier = Modifier.size(50.dp)
        ) {

            Text(
                text = "↑",
                fontSize = 25.sp,
                color = Color.White
            )
        }
    }
}