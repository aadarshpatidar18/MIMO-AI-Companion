"""The desktop shell, tested against a real backend.

The API client is not mocked: the server is started from `scripts/load_test.py --serve` (which
installs a deterministic fake model) and the client pairs, chats and stops tasks over real HTTP.
The window is exercised with Qt's offscreen platform, so the widgets are really constructed.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "desktop"))

from mimo_desktop.api import MimoApi, MimoError  # noqa: E402

pytest.importorskip("PySide6")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    port = _free_port()
    data = tmp_path_factory.mktemp("mimo-desktop-data")
    env = dict(os.environ)
    env["MIMO_DATA_DIR"] = str(data)
    env.pop("MIMO_REQUIRE_AUTH", None)
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "load_test.py"), "--serve", "--port", str(port)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
    )
    line = process.stdout.readline().strip()
    if line != "READY":
        process.kill()
        pytest.skip(f"backend did not start: {line}")
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if urllib.request.urlopen(base + "/health", timeout=1).status == 200:
                break
        except Exception:
            time.sleep(0.1)
    yield base
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


@pytest.fixture
def api(server):
    """A paired client: the code is issued from loopback, which the backend treats as the PC."""
    request = urllib.request.Request(
        server + "/auth/pair/code", data=b'{"kind": "desktop"}', method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        code = json.loads(response.read())["code"]
    client = MimoApi(server)
    device, token = client.pair(code, "Desktop test", "desktop")
    client.token = token
    return client, device


def test_pairing_returns_a_device_and_a_token(api):
    client, device = api
    assert device.kind == "desktop"
    assert token_like(client.token)
    me = client.me()
    assert me.id == device.id
    assert "chat:write" in me.scopes


def token_like(value: str) -> bool:
    return bool(value) and len(value) >= 20


def test_a_conversation_can_be_created_chatted_in_and_read(api):
    client, _ = api
    conversation = client.create_conversation("Desktop test")
    reply = client.chat(conversation["id"], "hello from the desktop")
    assert reply["response"]
    messages = client.messages(conversation["id"])
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "hello from the desktop"


def test_memory_can_be_taught_and_forgotten(api):
    client, _ = api
    client.remember("the desktop test likes strong coffee")
    found = [m for m in client.memory("strong coffee")]
    assert found, "the fact should be searchable immediately"
    client.forget("strong coffee")
    assert client.memory("strong coffee") == []


def test_emergency_stop_cancels_running_tasks(api):
    client, _ = api
    started = [client.start_task(f"desktop stop test {i}")["id"] for i in range(4)]
    result = client.stop_everything()
    assert "failed" in result
    for task_id in started:
        task = next(t for t in client.tasks() if t["id"] == task_id)
        assert task["status"] in ("cancelled", "succeeded", "failed")


def test_a_bad_token_is_a_readable_error(server):
    client = MimoApi(server, token="definitely-not-a-token")
    with pytest.raises(MimoError) as caught:
        client.conversations()
    assert caught.value.status in (401, 403)
    assert caught.value.is_auth


def test_an_unreachable_backend_is_an_offline_error_not_a_crash():
    client = MimoApi(f"http://127.0.0.1:{_free_port()}", token="x", timeout=2)
    assert client.health() is False
    with pytest.raises(MimoError) as caught:
        client.conversations()
    assert caught.value.is_offline


def test_the_window_builds_every_screen(server, tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from mimo_desktop.settings import DesktopSettings
    from mimo_desktop.window import MainWindow

    app = QApplication.instance() or QApplication([])
    settings = DesktopSettings(base_url=server)
    window = MainWindow(settings, MimoApi(server))
    window.show()
    app.processEvents()
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == [
        "Chat", "Activity", "Memory", "Devices", "Settings"
    ]
    window.append_bubble("a question", False)
    window.append_bubble("an answer", True)
    assert window.transcript.count() == 2
    assert window.stop_button.text() == "Emergency stop"
    window.close()
