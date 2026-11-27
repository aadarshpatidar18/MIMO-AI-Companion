"""The desktop shell's only way to reach MIMO: the same HTTP API the browser and the phone use.

No business logic lives here. If the desktop needs a capability, the backend grows a route — never
a second implementation in the client. That rule is what keeps three interfaces honest with each
other.
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional

DEFAULT_BASE = "http://127.0.0.1:8000"


class MimoError(Exception):
    """A failure the user can read. `status` is 0 when the backend was not reachable."""

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status

    @property
    def is_offline(self) -> bool:
        return self.status == 0

    @property
    def is_auth(self) -> bool:
        return self.status in (401, 403)


@dataclass
class Device:
    id: str
    name: str
    kind: str
    scopes: list[str]


class MimoApi:
    def __init__(self, base_url: str = DEFAULT_BASE, token: Optional[str] = None,
                 timeout: float = 180.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    # ---------------------------------------------------------------- plumbing
    def _request(self, method: str, path: str, body: Any = None,
                 raw: bool = False, authenticated: bool = True,
                 content_type: str = "application/json",
                 timeout: Optional[float] = None) -> Any:
        url = self.base_url + (path if path.startswith("/") else "/" + path)
        data = None
        headers = {"Accept": "audio/wav" if raw else "application/json"}
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
            headers["Content-Type"] = content_type
        if authenticated and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                payload = response.read()
                if raw:
                    return payload
                return json.loads(payload.decode("utf-8")) if payload else {}
        except urllib.error.HTTPError as error:
            detail = ""
            try:
                parsed = json.loads(error.read().decode("utf-8"))
                detail = parsed.get("detail") if isinstance(parsed, dict) else ""
                if isinstance(detail, list):
                    detail = "; ".join(str(item) for item in detail)
            except Exception:
                detail = ""
            raise MimoError(detail or f"MIMO answered {error.code}.", error.code) from None
        except urllib.error.URLError as error:
            raise MimoError(f"Can't reach MIMO at {self.base_url}. {error.reason}") from None
        except (socket.timeout, TimeoutError):
            raise MimoError("MIMO took too long to answer.") from None
        except json.JSONDecodeError:
            raise MimoError("MIMO sent a response this app could not read.", 500) from None

    # ------------------------------------------------------------------- verbs
    def health(self) -> bool:
        try:
            self._request("GET", "/health", authenticated=False, timeout=6)
            return True
        except MimoError:
            return False

    def auth_status(self) -> dict:
        return self._request("GET", "/auth/status", authenticated=False)

    def pair(self, code: str, name: str = "Windows desktop",
             kind: str = "desktop") -> tuple[Device, str]:
        result = self._request("POST", "/auth/pair",
                               {"code": code.strip().upper(), "name": name, "kind": kind},
                               authenticated=False)
        device = result["device"]
        return Device(device["id"], device.get("name", name), device.get("kind", kind),
                      list(device.get("scopes", []))), result["token"]

    def me(self) -> Device:
        device = self._request("GET", "/auth/me")
        return Device(device["id"], device.get("name", ""), device.get("kind", ""),
                      list(device.get("scopes", [])))

    def devices(self) -> list[dict]:
        return self._request("GET", "/devices").get("devices", [])

    def revoke(self, device_id: str) -> None:
        self._request("DELETE", f"/devices/{device_id}")

    def conversations(self, limit: int = 50) -> list[dict]:
        return self._request("GET", f"/conversations?limit={limit}").get("conversations", [])

    def create_conversation(self, title: str = "") -> dict:
        return self._request("POST", "/conversations", {"title": title})

    def delete_conversation(self, conversation_id: str) -> None:
        self._request("DELETE", f"/conversations/{conversation_id}")

    def messages(self, conversation_id: str, after_id: int = 0, limit: int = 200) -> list[dict]:
        return self._request(
            "GET", f"/conversations/{conversation_id}/messages?after_id={after_id}&limit={limit}"
        ).get("messages", [])

    def chat(self, conversation_id: str, message: str) -> dict:
        return self._request("POST", "/chat",
                             {"message": message, "conversation_id": conversation_id,
                              "session_id": "desktop"})

    def memory(self, keyword: str = "") -> list[dict]:
        query = urllib.parse.urlencode({"keyword": keyword}) if keyword else ""
        return self._request("GET", f"/memory?{query}" if query else "/memory").get("memories", [])

    def remember(self, content: str, category: Optional[str] = None) -> dict:
        body: dict = {"content": content}
        if category:
            body["category"] = category
        return self._request("POST", "/memory", body)

    def correct_memory(self, memory_id: int, content: Optional[str] = None,
                       importance: Optional[int] = None) -> dict:
        body = {k: v for k, v in (("content", content), ("importance", importance))
                if v is not None}
        return self._request("PUT", f"/memory/{memory_id}", body)

    def forget(self, keyword: str) -> dict:
        return self._request("DELETE", "/memory", {"keyword": keyword})

    def tasks(self, limit: int = 50) -> list[dict]:
        return self._request("GET", f"/agent/tasks?limit={limit}").get("tasks", [])

    def start_task(self, goal: str, agent: Optional[str] = None) -> dict:
        return self._request("POST", "/agent/tasks", {"goal": goal, "agent": agent})

    def cancel_task(self, task_id: str) -> dict:
        return self._request("POST", f"/agent/tasks/{task_id}/cancel")

    def confirm_task(self, task_id: str, approve: bool) -> dict:
        return self._request("POST", f"/agent/tasks/{task_id}/confirm", {"approve": approve})

    def stop_everything(self) -> dict:
        """Emergency stop: cancel every task that is still running, and say what was stopped."""
        stopped, failed = [], []
        for task in self.tasks(limit=100):
            if task.get("status") in ("queued", "running", "planning"):
                try:
                    self.cancel_task(task["id"])
                    stopped.append(task["id"])
                except MimoError as error:
                    failed.append(f"{task['id']}: {error}")
        return {"stopped": stopped, "failed": failed}

    def speak(self, text: str) -> bytes:
        return self._request("POST", "/voice/speak", {"text": text}, raw=True)

    def transcribe(self, wav: bytes) -> dict:
        return self._request("POST", "/voice/transcribe", wav,
                             content_type="audio/wav")
