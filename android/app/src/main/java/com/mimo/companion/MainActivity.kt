package com.mimo.companion

import android.os.Bundle
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
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.mimo.companion.data.model.ChatMessage
import com.mimo.companion.ui.theme.MIMOTheme
import com.mimo.companion.viewmodel.MimoViewModel

private val Background = Color(0xFF0D1117)
private val SurfaceColor = Color(0xFF161B22)
private val Accent = Color(0xFF7C9CFF)
private val PrimaryText = Color(0xFFF0F3F8)
private val SecondaryText = Color(0xFF929BAA)

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
fun MimoChatScreen(
    mimoViewModel: MimoViewModel = viewModel()
) {

    val uiState by mimoViewModel.uiState.collectAsStateWithLifecycle()

    val listState = rememberLazyListState()

    Scaffold(
        containerColor = Background,
        modifier = Modifier.fillMaxSize(),
        bottomBar = {
            MessageInput(
                input = uiState.input,
                onInputChange = mimoViewModel::updateInput,
                onSend = mimoViewModel::sendMessage,
                isLoading = uiState.isLoading
            )
        }
    ) { padding ->

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
        ) {

            MimoHeader(uiState.isConnected)

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

                items(uiState.messages) { message ->
                    MessageBubble(message)
                }

                if (uiState.isLoading) {
                    item {
                        Text(
                            text = "MIMO is thinking...",
                            color = SecondaryText,
                            fontSize = 12.sp
                        )
                    }
                }
            }

            LaunchedEffect(uiState.messages.size, uiState.isLoading) {
                val lastIndex = if (uiState.isLoading) {
                    uiState.messages.size + 1
                } else {
                    uiState.messages.size
                }

                if (lastIndex > 0) {
                    listState.animateScrollToItem(lastIndex)
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