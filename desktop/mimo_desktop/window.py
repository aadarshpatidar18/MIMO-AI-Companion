"""The main window: chat, activity, memory, devices, settings — and one red button.

Every screen here calls the same backend the browser and the phone call. Nothing is cached that the
backend already owns, except the conversation list on screen, so a correction made on the phone is
what the desktop shows after a refresh.
"""
from __future__ import annotations

import html
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
                               QPushButton, QSizePolicy, QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from .api import Device, MimoApi, MimoError
from .settings import DesktopSettings, save_settings
from .theme import QSS
from .worker import run_async

RUNNING = ("queued", "running", "planning")


class MainWindow(QMainWindow):
    def __init__(self, settings: DesktopSettings, api: Optional[MimoApi] = None) -> None:
        super().__init__()
        self.settings = settings
        self.api = api or MimoApi(settings.base_url, settings.token)
        self.current_conversation: Optional[str] = None
        self.last_answer = ""
        self.player = None
        self.audio_output = None
        self._audio_buffer = None
        self._task_rows: dict[str, int] = {}

        self.setWindowTitle("MIMO")
        self.resize(1120, 760)
        self.setStyleSheet(QSS)
        self._build_toolbar()
        self._build_tabs()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_tasks_silently)
        self.timer.start(4_000)
        self.check_connection()
        self.load_conversations()
        self.load_memory()
        self.load_devices()

    # ------------------------------------------------------------------ chrome
    def _build_toolbar(self) -> None:
        bar = self.addToolBar("MIMO")
        bar.setMovable(False)
        bar.setStyleSheet("QToolBar { background: #1a1d23; spacing: 8px; padding: 6px; }")

        title = QLabel("  MIMO")
        font = QFont()
        font.setPointSize(13)
        font.setBold(True)
        title.setFont(font)
        bar.addWidget(title)
        bar.addSeparator()

        self.status = QLabel("Checking…")
        self.status.setObjectName("status")
        bar.addWidget(self.status)
        self.identity = QLabel("")
        self.identity.setObjectName("muted")
        bar.addWidget(self.identity)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(spacer)

        self.stop_button = QPushButton("Emergency stop")
        self.stop_button.setObjectName("danger")
        self.stop_button.setToolTip("Cancel every running task right now")
        self.stop_button.clicked.connect(self.emergency_stop)
        bar.addWidget(self.stop_button)

    def _build_tabs(self) -> None:
        self.tabs = QTabWidget()
        self.tabs.addTab(self._chat_tab(), "Chat")
        self.tabs.addTab(self._activity_tab(), "Activity")
        self.tabs.addTab(self._memory_tab(), "Memory")
        self.tabs.addTab(self._devices_tab(), "Devices")
        self.tabs.addTab(self._settings_tab(), "Settings")
        self.setCentralWidget(self.tabs)

    # -------------------------------------------------------------------- chat
    def _chat_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        top = QHBoxLayout()
        self.conversation_box = QComboBox()
        self.conversation_box.currentIndexChanged.connect(self.on_conversation_changed)
        top.addWidget(self.conversation_box, 1)
        new_button = QPushButton("New chat")
        new_button.clicked.connect(self.new_conversation)
        top.addWidget(new_button)
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(self.delete_conversation)
        top.addWidget(delete_button)
        layout.addLayout(top)

        self.transcript = QListWidget()
        self.transcript.setWordWrap(True)
        self.transcript.setSelectionMode(QListWidget.NoSelection)
        layout.addWidget(self.transcript, 1)

        bottom = QHBoxLayout()
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("Message MIMO…  (Ctrl+Enter to send)")
        self.input.setFixedHeight(84)
        bottom.addWidget(self.input, 1)
        column = QVBoxLayout()
        send = QPushButton("Send")
        send.setObjectName("primary")
        send.clicked.connect(self.send_message)
        column.addWidget(send)
        self.speak_button = QPushButton("Speak")
        self.speak_button.setToolTip("Read the last answer aloud (needs local voice on the PC)")
        self.speak_button.clicked.connect(self.speak_last_answer)
        column.addWidget(self.speak_button)
        bottom.addLayout(column)
        layout.addLayout(bottom)
        return page

    def load_conversations(self) -> None:
        def done(conversations: list[dict]) -> None:
            self.conversation_box.blockSignals(True)
            self.conversation_box.clear()
            for conversation in conversations:
                label = conversation.get("title") or "Conversation"
                self.conversation_box.addItem(label[:60], conversation["id"])
            self.conversation_box.blockSignals(False)
            if conversations:
                self.current_conversation = conversations[0]["id"]
                self.conversation_box.setCurrentIndex(0)
                self.load_messages()

        run_async(self.api.conversations, done, self.show_error)

    def on_conversation_changed(self, index: int) -> None:
        if index < 0:
            return
        conversation_id = self.conversation_box.itemData(index)
        if conversation_id and conversation_id != self.current_conversation:
            self.current_conversation = conversation_id
            self.load_messages()

    def load_messages(self) -> None:
        conversation_id = self.current_conversation
        if not conversation_id:
            self.transcript.clear()
            return

        def done(messages: list[dict]) -> None:
            if conversation_id != self.current_conversation:
                return
            self.transcript.clear()
            for message in messages:
                self.append_bubble(message.get("content", ""), message.get("role") == "assistant")

        run_async(self.api.messages, done, self.show_error, conversation_id)

    def append_bubble(self, text: str, from_mimo: bool) -> None:
        if not from_mimo:
            prefix = "<b style='color:#8ab4f8'>You</b><br>"
            background = "#1d2430"
        else:
            prefix = "<b style='color:#58d27d'>MIMO</b><br>"
            background = "#1a1d23"
        body = html.escape(text).replace("\n", "<br>")
        item = QListWidgetItem()
        label = QLabel(f"<div style='background:{background}; padding:10px; border-radius:8px;'>"
                       f"{prefix}{body}</div>")
        label.setWordWrap(True)
        label.setTextFormat(Qt.RichText)
        item.setSizeHint(label.sizeHint())
        self.transcript.addItem(item)
        self.transcript.setItemWidget(item, label)
        self.transcript.scrollToBottom()

    def send_message(self) -> None:
        text = self.input.toPlainText().strip()
        if not text:
            return
        self.input.clear()
        self.append_bubble(text, False)

        def deliver(conversation_id: str) -> None:
            self.api.chat(conversation_id, text)          # runs in the worker thread

        def on_done(response: dict) -> None:
            self.last_answer = response.get("response", "")
            self.append_bubble(self.last_answer, True)
            self.load_conversations()
            if self.settings.speak_replies:
                self.speak_last_answer()

        def on_error(message: str) -> None:
            self.append_bubble(f"[not delivered] {message}", True)
            self.show_error(message)

        if self.current_conversation:
            run_async(lambda: self.api.chat(self.current_conversation, text), on_done, on_error)
        else:
            def create_and_send() -> dict:
                conversation = self.api.create_conversation(text[:60])
                self.current_conversation = conversation["id"]
                return self.api.chat(conversation["id"], text)

            run_async(create_and_send, on_done, on_error)

    def new_conversation(self) -> None:
        def done(conversation: dict) -> None:
            self.current_conversation = conversation["id"]
            self.transcript.clear()
            self.load_conversations()

        run_async(lambda: self.api.create_conversation(), done, self.show_error)

    def delete_conversation(self) -> None:
        if not self.current_conversation:
            return
        if QMessageBox.question(self, "Delete conversation",
                                "Delete this conversation from every paired device?") != \
                QMessageBox.Yes:
            return
        conversation_id = self.current_conversation

        def done(_: None) -> None:
            self.current_conversation = None
            self.transcript.clear()
            self.load_conversations()

        run_async(lambda: self.api.delete_conversation(conversation_id), done, self.show_error)

    def speak_last_answer(self) -> None:
        """Ask the backend for speech and play it here.

        The synthesis happens on the PC's own Kokoro model; this window only plays the WAV it
        returns. If Qt cannot open an audio device (a headless session, no sound card), that is
        reported instead of pretending something was said.
        """
        text = self.last_answer or "MIMO is ready."
        run_async(lambda: self.api.speak(text), self.play_audio, self.show_error)

    def play_audio(self, audio: bytes) -> None:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QUrl
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

        try:
            if self.player is None:
                self.player = QMediaPlayer(self)
                self.audio_output = QAudioOutput(self)
                self.player.setAudioOutput(self.audio_output)
                self.audio_output.setVolume(0.8)
            buffer = QBuffer(self)
            buffer.setData(QByteArray(audio))
            buffer.open(QIODevice.ReadOnly)
            self._audio_buffer = buffer          # keep it alive while playing
            self.player.setSourceDevice(buffer, QUrl("audio/wav"))
            self.player.play()
        except Exception as error:
            self.show_error(f"Could not play the answer here ({error}). The browser interface can.")

    # ---------------------------------------------------------------- activity
    def _activity_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.goal_input = QLineEdit()
        self.goal_input.setPlaceholderText("Give MIMO a goal…")
        row.addWidget(self.goal_input, 1)
        start = QPushButton("Start task")
        start.setObjectName("primary")
        start.clicked.connect(self.start_task)
        row.addWidget(start)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.load_tasks)
        row.addWidget(refresh)
        layout.addLayout(row)

        self.task_table = QTableWidget(0, 5)
        self.task_table.setHorizontalHeaderLabels(["Goal", "Agent", "Status", "Started", ""])
        self.task_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.task_table.verticalHeader().setVisible(False)
        self.task_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.task_table, 1)
        self.load_tasks()
        return page

    def load_tasks(self) -> None:
        run_async(self.api.tasks, self.render_tasks, self.show_error)

    def refresh_tasks_silently(self) -> None:
        if not self.api.token:
            return

        def done(tasks: list[dict]) -> None:
            self.render_tasks(tasks)

        def ignore(_message: str) -> None:
            return

        run_async(self.api.tasks, done, ignore)

    def render_tasks(self, tasks: list[dict]) -> None:
        self._task_rows.clear()
        self.task_table.setRowCount(len(tasks))
        for row, task in enumerate(tasks):
            self._task_rows[task["id"]] = row
            self.task_table.setItem(row, 0, QTableWidgetItem(task.get("goal", "")[:120]))
            self.task_table.setItem(row, 1, QTableWidgetItem(
                task.get("agent_key") or task.get("agent") or "generalist"))
            status = task.get("status", "")
            self.task_table.setItem(row, 2, QTableWidgetItem(status.replace("_", " ")))
            self.task_table.setItem(row, 3, QTableWidgetItem((task.get("created_at") or "")[:19]))
            if status in RUNNING or task.get("pending"):
                actions = QWidget()
                box = QHBoxLayout(actions)
                box.setContentsMargins(0, 0, 0, 0)
                if task.get("pending"):
                    approve = QPushButton("Approve")
                    approve.clicked.connect(lambda _, t=task["id"]: self.confirm_task(t, True))
                    box.addWidget(approve)
                    deny = QPushButton("Deny")
                    deny.clicked.connect(lambda _, t=task["id"]: self.confirm_task(t, False))
                    box.addWidget(deny)
                if status in RUNNING:
                    stop = QPushButton("Stop")
                    stop.clicked.connect(lambda _, t=task["id"]: self.cancel_task(t))
                    box.addWidget(stop)
                self.task_table.setCellWidget(row, 4, actions)

    def start_task(self) -> None:
        goal = self.goal_input.text().strip()
        if not goal:
            return
        self.goal_input.clear()
        run_async(lambda: self.api.start_task(goal), lambda _: self.load_tasks(), self.show_error)

    def cancel_task(self, task_id: str) -> None:
        run_async(lambda: self.api.cancel_task(task_id), lambda _: self.load_tasks(),
                  self.show_error)

    def confirm_task(self, task_id: str, approve: bool) -> None:
        run_async(lambda: self.api.confirm_task(task_id, approve),
                  lambda _: self.load_tasks(), self.show_error)

    def emergency_stop(self) -> None:
        def done(result: dict) -> None:
            count = len(result.get("stopped", []))
            failed = result.get("failed", [])
            message = f"Stopped {count} task(s)." if count else "Nothing was running."
            if failed:
                message += " Could not stop: " + "; ".join(failed)
            QMessageBox.information(self, "Emergency stop", message)
            self.load_tasks()

        run_async(self.api.stop_everything, done, self.show_error)

    # ------------------------------------------------------------------ memory
    def _memory_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.memory_search = QLineEdit()
        self.memory_search.setPlaceholderText("Search what MIMO remembers…")
        self.memory_search.returnPressed.connect(self.load_memory)
        row.addWidget(self.memory_search, 1)
        search = QPushButton("Search")
        search.clicked.connect(self.load_memory)
        row.addWidget(search)
        self.memory_new = QLineEdit()
        self.memory_new.setPlaceholderText("Teach MIMO a fact…")
        row.addWidget(self.memory_new, 1)
        add = QPushButton("Remember")
        add.clicked.connect(self.add_memory)
        row.addWidget(add)
        layout.addLayout(row)

        self.memory_list = QListWidget()
        self.memory_list.itemDoubleClicked.connect(self.correct_memory)
        layout.addWidget(self.memory_list, 1)
        hint = QLabel("Double-click a fact to change it; importance 1–5 decides what gets recalled first.")
        hint.setObjectName("muted")
        layout.addWidget(hint)
        return page

    def load_memory(self) -> None:
        keyword = self.memory_search.text().strip()

        def done(memories: list[dict]) -> None:
            self.memory_list.clear()
            for memory in memories:
                item = QListWidgetItem(
                    f"[{memory.get('importance', 3)}] {memory.get('category', '')} · "
                    f"{memory.get('content', '')}"
                )
                item.setData(Qt.UserRole, memory)
                self.memory_list.addItem(item)

        run_async(lambda: self.api.memory(keyword), done, self.show_error)

    def add_memory(self) -> None:
        content = self.memory_new.text().strip()
        if not content:
            return
        self.memory_new.clear()
        run_async(lambda: self.api.remember(content), lambda _: self.load_memory(), self.show_error)

    def correct_memory(self, item: QListWidgetItem) -> None:
        memory = item.data(Qt.UserRole) or {}
        from PySide6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getText(self, "Correct this memory", "Wording:",
                                        text=memory.get("content", ""))
        if not ok or not text.strip():
            return
        importance, accepted = QInputDialog.getInt(
            self, "Importance", "How much does this matter? (1–5)",
            int(memory.get("importance", 3)), 1, 5
        )
        if not accepted:
            return
        run_async(lambda: self.api.correct_memory(memory["id"], text.strip(), importance),
                  lambda _: self.load_memory(), self.show_error)

    # ----------------------------------------------------------------- devices
    def _devices_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.device_table = QTableWidget(0, 5)
        self.device_table.setHorizontalHeaderLabels(["Name", "Kind", "Scopes", "Last seen", ""])
        self.device_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.device_table.verticalHeader().setVisible(False)
        self.device_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.device_table, 1)
        refresh = QPushButton("Refresh devices")
        refresh.clicked.connect(self.load_devices)
        layout.addWidget(refresh, alignment=Qt.AlignLeft)
        return page

    def load_devices(self) -> None:
        if not self.api.token:
            self.device_table.setRowCount(0)
            return

        def done(devices: list[dict]) -> None:
            self.device_table.setRowCount(len(devices))
            for row, device in enumerate(devices):
                self.device_table.setItem(row, 0, QTableWidgetItem(device.get("name", "")))
                self.device_table.setItem(row, 1, QTableWidgetItem(device.get("kind", "")))
                self.device_table.setItem(row, 2, QTableWidgetItem(
                    ", ".join(device.get("scopes", []) or [])))
                self.device_table.setItem(row, 3, QTableWidgetItem(
                    (device.get("last_seen") or "")[:19]))
                if not device.get("revoked"):
                    revoke = QPushButton("Revoke")
                    revoke.clicked.connect(lambda _, d=device["id"]: self.revoke_device(d))
                    self.device_table.setCellWidget(row, 4, revoke)

        run_async(self.api.devices, done, self.show_error)

    def revoke_device(self, device_id: str) -> None:
        if QMessageBox.question(self, "Revoke device",
                                "This device will lose access immediately. Continue?") != \
                QMessageBox.Yes:
            return
        run_async(lambda: self.api.revoke(device_id), lambda _: self.load_devices(),
                  self.show_error)

    # ---------------------------------------------------------------- settings
    def _settings_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addWidget(self._heading("Backend"))
        row = QHBoxLayout()
        self.url_input = QLineEdit(self.settings.base_url)
        row.addWidget(self.url_input, 1)
        save = QPushButton("Save address")
        save.clicked.connect(self.save_address)
        row.addWidget(save)
        layout.addLayout(row)

        layout.addWidget(self._heading("Pair this PC"))
        pair_hint = QLabel("On the MIMO PC run  python -m backend.main pair  and type the code here.")
        pair_hint.setObjectName("muted")
        layout.addWidget(pair_hint)
        pair_row = QHBoxLayout()
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("Pairing code")
        self.code_input.setMaxLength(12)
        pair_row.addWidget(self.code_input, 1)
        pair = QPushButton("Pair")
        pair.setObjectName("primary")
        pair.clicked.connect(self.pair)
        pair_row.addWidget(pair)
        layout.addLayout(pair_row)

        self.paired_label = QLabel("")
        self.paired_label.setObjectName("muted")
        layout.addWidget(self.paired_label)

        layout.addWidget(self._heading("Voice"))
        self.speak_toggle = QPushButton()
        self.speak_toggle.setCheckable(True)
        self.speak_toggle.setChecked(self.settings.speak_replies)
        self.speak_toggle.setText("Speak replies aloud" if self.settings.speak_replies
                                  else "Spoken replies off")
        self.speak_toggle.clicked.connect(self.toggle_speech)
        layout.addWidget(self.speak_toggle, alignment=Qt.AlignLeft)

        layout.addStretch(1)
        self.refresh_identity()
        return page

    def _heading(self, text: str) -> QLabel:
        label = QLabel(text)
        font = QFont()
        font.setBold(True)
        label.setFont(font)
        label.setStyleSheet("margin-top: 14px;")
        return label

    def refresh_identity(self) -> None:
        if not self.settings.is_paired:
            self.paired_label.setText("Not paired yet — MIMO cannot be used until this PC has a token.")
            self.identity.setText("")
            return
        self.paired_label.setText(f"Paired as {self.settings.device_name}.")

        def done(device: Device) -> None:
            self.paired_label.setText(
                f"Paired as {device.name} · scopes: {', '.join(device.scopes) or 'none'}")
            self.identity.setText(f"  {device.name} ")

        def failed(message: str) -> None:
            if "401" in message or "token" in message.lower():
                self.paired_label.setText("This PC's token is no longer valid — pair again.")

        run_async(self.api.me, done, failed)

    def save_address(self) -> None:
        url = self.url_input.text().strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            self.show_error("The address must start with http:// or https://")
            return
        self.settings.base_url = url.rstrip("/")
        save_settings(self.settings)
        run_async(self.api.health, lambda ok: self.check_connection(), self.show_error)

    def pair(self) -> None:
        code = self.code_input.text().strip()
        if len(code) < 4:
            self.show_error("Type the code the PC printed.")
            return
        base = self.url_input.text().strip().rstrip("/")
        self.api.base_url = base

        def do_pair() -> tuple[Device, str]:
            return self.api.pair(code, self.settings.device_name or "Windows desktop")

        def done(result: tuple[Device, str]) -> None:
            device, token = result
            self.settings.base_url = base
            self.settings.token = token
            self.settings.device_id = device.id
            self.settings.device_name = device.name or self.settings.device_name
            save_settings(self.settings)
            self.api.token = token
            self.code_input.clear()
            self.refresh_identity()
            self.check_connection()
            self.load_conversations()
            self.load_devices()

        run_async(do_pair, done, self.show_error)

    def toggle_speech(self) -> None:
        self.settings.speak_replies = self.speak_toggle.isChecked()
        self.speak_toggle.setText("Speak replies aloud" if self.settings.speak_replies
                                  else "Spoken replies off")
        save_settings(self.settings)

    # ------------------------------------------------------------------ status
    def check_connection(self) -> None:
        def done(online: bool) -> None:
            if online and self.settings.is_paired:
                self.status.setText("● Connected")
                self.status.setObjectName("statusOnline")
            elif online:
                self.status.setText("● Online, not paired")
                self.status.setObjectName("status")
            else:
                self.status.setText("● Offline")
                self.status.setObjectName("statusOffline")
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)

        run_async(self.api.health, done, lambda _: done(False))

    def show_error(self, message: str) -> None:
        self.statusBar().showMessage(message, 8_000)
