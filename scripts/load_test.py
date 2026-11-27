"""Load and resilience measurement for MIMO's own machinery.

    python scripts/load_test.py                  # full run, prints a report
    python scripts/load_test.py --json report.json

The language model is replaced with a deterministic fake, on purpose: this measures what MIMO adds
— HTTP, SQLite, the agent engine, the policy layer — instead of the speed of whichever model is
installed. Model latency is measured separately (docs/VOICE.md, docs/MODEL_ROUTING.md); mixing the
two would hide MIMO's own cost inside a number that says nothing about it.

The server runs in its own process so its memory and CPU can be read honestly, and every number
printed was measured in this run.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DATA_DIR = os.environ.get("MIMO_LOADTEST_DATA") or tempfile.mkdtemp(prefix="mimo-load-")


def _install_fake_model() -> None:
    """A provider that answers instantly and deterministically, so the rest can be measured."""
    import backend.core.llm as llm_pkg
    from backend.core.llm.base import LLMProvider, LLMResponse
    from backend.core.llm.config import RouterSettings, default_routes
    from backend.core.llm.retry import RetryPolicy
    from backend.core.llm.router import ModelRouter
    from backend.core.llm.usage import UsageTracker

    class Fake(LLMProvider):
        def __init__(self, name="fake", local=True):
            self.name, self.is_local, self.default_model = name, local, "fake-1"

        def is_configured(self):
            return True

        def generate(self, request, model=None):
            if request.task == "intent":
                text = json.dumps({"intent": "general_question", "parameters": {}})
            elif request.task == "plan":
                text = json.dumps({"steps": []})
            else:
                text = f"fake answer to: {request.messages[-1].content[-60:]}"
            return LLMResponse(text=text, provider=self.name,
                               model=model or self.default_model)

    providers = {"gemini": Fake("gemini", False), "ollama": Fake("ollama", True)}
    settings = RouterSettings(
        selection="auto",
        routes=default_routes(),
        retry={name: RetryPolicy(max_attempts=1) for name in providers},
    )
    llm_pkg._router = ModelRouter(providers, settings, UsageTracker(), sleep=lambda s: None)


def serve(port: int) -> int:
    # The parent decides where the database lives and passes it down; only stand one up when the
    # server was launched on its own.
    os.environ.setdefault("MIMO_DATA_DIR", DATA_DIR)
    os.environ.pop("MIMO_REQUIRE_AUTH", None)
    _install_fake_model()
    import uvicorn

    from backend.api import app

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error",
                            lifespan="on", access_log=False)
    server = uvicorn.Server(config)
    print("READY", flush=True)
    server.run()
    return 0


# ------------------------------------------------------------------------- client
class Client:
    def __init__(self, base: str, token: str) -> None:
        import httpx

        self.base = base
        self.token = token
        self._client = httpx.AsyncClient(base_url=base, timeout=180.0)
        self.headers = {"Authorization": f"Bearer {token}"}

    async def close(self) -> None:
        await self._client.aclose()

    async def request(self, method: str, path: str, **kwargs):
        headers = dict(self.headers)
        headers.update(kwargs.pop("headers", {}) or {})
        started = time.perf_counter()
        response = await self._client.request(method, path, headers=headers, **kwargs)
        return response, (time.perf_counter() - started) * 1000.0

    async def conversation(self) -> str:
        response, _ = await self.request("POST", "/conversations", json={})
        response.raise_for_status()
        return response.json()["id"]


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(int(round((p / 100.0) * (len(ordered) - 1))), len(ordered) - 1)
    return ordered[index]


# ---------------------------------------------------------------------- scenarios
async def scenario_sequential(client: Client, turns: int = 40) -> dict:
    conversation = await client.conversation()
    latencies = []
    for index in range(turns):
        response, ms = await client.request(
            "POST", "/chat",
            json={"message": f"turn {index}", "conversation_id": conversation},
        )
        response.raise_for_status()
        latencies.append(ms)
    return {"turns": turns, "latencies": latencies}


async def scenario_concurrent(base: str, tokens: list[str], per_worker: int = 10) -> dict:
    """Several paired devices talking at once — one client per device.

    Each worker gets its own device token on purpose. MIMO rate-limits per device (which is the
    correct behaviour) and a single device hammering the API would only measure that limit.
    """
    clients = [Client(base, token) for token in tokens]
    conversations = [await client.conversation() for client in clients]
    latencies: list[float] = []
    rejections: list[int] = []
    lock = asyncio.Lock()

    async def worker(client: Client, conversation: str, index: int) -> None:
        for turn in range(per_worker):
            response, ms = await client.request(
                "POST", "/chat",
                json={"message": f"w{index} t{turn}", "conversation_id": conversation},
            )
            async with lock:
                if response.status_code == 200:
                    latencies.append(ms)
                else:
                    rejections.append(response.status_code)

    started = time.perf_counter()
    try:
        await asyncio.gather(*(worker(clients[i], conversations[i], i) for i in range(len(clients))))
    finally:
        for client in clients:
            await client.close()
    elapsed = time.perf_counter() - started
    total = len(clients) * per_worker
    return {
        "workers": len(clients),
        "turns": total,
        "elapsed_s": round(elapsed, 2),
        "throughput_rps": round(len(latencies) / elapsed, 1) if elapsed else 0.0,
        "rejections": {str(code): rejections.count(code) for code in set(rejections)},
        "latencies": latencies,
    }


async def scenario_long_conversation(client: Client, messages: int = 200) -> dict:
    conversation = await client.conversation()
    for index in range(messages):
        await client.request(
            "POST", f"/conversations/{conversation}/messages",
            json={"role": "user" if index % 2 == 0 else "assistant", "content": f"line {index}"},
        )
    _, read_ms = await client.request(
        "GET", f"/conversations/{conversation}/messages?limit=200"
    )
    response, chat_ms = await client.request(
        "POST", "/chat", json={"message": "and now?", "conversation_id": conversation}
    )
    response.raise_for_status()
    return {"messages": messages, "read_all_ms": read_ms, "chat_with_history_ms": chat_ms}


async def scenario_memory(client: Client, facts: int = 300, queries: int = 20) -> dict:
    for index in range(facts):
        await client.request(
            "POST", "/memory",
            json={"content": f"load fact {index} about project robotics number {index}",
                  "category": "project"},
        )
    latencies = []
    for index in range(queries):
        _, ms = await client.request("GET", f"/memory?keyword=robotics%20number%20{index}")
        latencies.append(ms)
    return {"facts": facts, "queries": queries, "latencies": latencies}


async def scenario_duplicates(client: Client, concurrent: int = 20) -> dict:
    """The same turn posted at the same moment must not be lost or duplicated."""
    conversation = await client.conversation()
    body = {"message": "duplicate storm", "conversation_id": conversation}

    async def one() -> int:
        response, _ = await client.request("POST", "/chat", json=body)
        return response.status_code

    statuses = await asyncio.gather(*(one() for _ in range(concurrent)))
    response, _ = await client.request("GET", f"/conversations/{conversation}/messages?limit=500")
    messages = response.json()["messages"]
    ids = [m["id"] for m in messages]
    return {
        "requests": concurrent,
        "statuses": {str(code): statuses.count(code) for code in set(statuses)},
        "stored_messages": len(messages),
        "unique_ids": len(set(ids)),
    }


async def scenario_auth_failures(client: Client, attempts: int = 30) -> dict:
    latencies = []
    codes: list[int] = []
    for _ in range(attempts):
        response, ms = await client.request(
            "GET", "/conversations", headers={"Authorization": "Bearer not-a-real-token"}
        )
        codes.append(response.status_code)
        latencies.append(ms)
    return {"attempts": attempts, "statuses": {str(c): codes.count(c) for c in set(codes)},
            "latencies": latencies}


async def scenario_agents(client: Client, tasks: int = 8) -> dict:
    """Submit several agent goals at once; the engine must run them and finish every one."""
    goals = [f"check load task {index}" for index in range(tasks)]
    started = time.perf_counter()
    ids = []
    for goal in goals:
        response, _ = await client.request("POST", "/agent/tasks", json={"goal": goal})
        if response.status_code == 202:
            ids.append(response.json()["id"])
    outcomes: list[str] = []
    deadline = time.perf_counter() + 60
    while ids and time.perf_counter() < deadline:
        still: list[str] = []
        for task_id in ids:
            response, _ = await client.request("GET", f"/agent/tasks/{task_id}")
            status = response.json()["status"]
            if status in ("queued", "running", "planning"):
                still.append(task_id)
            else:
                outcomes.append(status)
        ids = still
        if ids:
            await asyncio.sleep(0.25)
    return {
        "submitted": tasks,
        "finished": len(outcomes),
        "statuses": {s: outcomes.count(s) for s in set(outcomes)},
        "unfinished": len(ids),
        "elapsed_s": round(time.perf_counter() - started, 2),
    }


async def scenario_cancel(client: Client) -> dict:
    response, _ = await client.request("POST", "/agent/tasks", json={"goal": "cancel me"})
    if response.status_code != 202:
        return {"skipped": response.status_code}
    task_id = response.json()["id"]
    started = time.perf_counter()
    await client.request("POST", f"/agent/tasks/{task_id}/cancel")
    final = "unknown"
    for _ in range(40):
        state, _ = await client.request("GET", f"/agent/tasks/{task_id}")
        final = state.json()["status"]
        if final not in ("queued", "running", "planning"):
            break
        await asyncio.sleep(0.1)
    return {"status": final, "stop_latency_ms": round((time.perf_counter() - started) * 1000, 1)}


# -------------------------------------------------------------------- reporting
def summarise(latencies: list[float]) -> dict:
    if not latencies:
        return {}
    return {
        "count": len(latencies),
        "mean_ms": round(statistics.fmean(latencies), 1),
        "p50_ms": round(percentile(latencies, 50), 1),
        "p95_ms": round(percentile(latencies, 95), 1),
        "p99_ms": round(percentile(latencies, 99), 1),
        "max_ms": round(max(latencies), 1),
    }


async def run(port: int, token: str, extra_tokens: list[str]) -> dict:
    import httpx  # noqa: F401  (fail early with a clear message)

    client = Client(f"http://127.0.0.1:{port}", token)
    results: dict = {"scenarios": {}}
    try:
        sequential = await scenario_sequential(client)
        results["scenarios"]["sequential_chat"] = {
            "turns": sequential["turns"],
            "latency": summarise(sequential["latencies"]),
            "throughput_rps": round(
                sequential["turns"] / max(sum(sequential["latencies"]) / 1000.0, 1e-9), 1
            ),
        }
        concurrent = await scenario_concurrent(
            f"http://127.0.0.1:{port}", [token] + extra_tokens
        )
        results["scenarios"]["concurrent_chat"] = {
            "workers": concurrent["workers"], "turns": concurrent["turns"],
            "elapsed_s": concurrent["elapsed_s"], "throughput_rps": concurrent["throughput_rps"],
            "rejections": concurrent["rejections"],
            "latency": summarise(concurrent["latencies"]),
        }
        results["scenarios"]["long_conversation"] = await scenario_long_conversation(client)
        memory = await scenario_memory(client)
        results["scenarios"]["memory_search"] = {
            "facts": memory["facts"], "queries": memory["queries"],
            "latency": summarise(memory["latencies"]),
        }
        results["scenarios"]["duplicate_requests"] = await scenario_duplicates(client)
        auth = await scenario_auth_failures(client)
        results["scenarios"]["auth_failures"] = {
            "attempts": auth["attempts"], "statuses": auth["statuses"],
            "latency": summarise(auth["latencies"]),
        }
        results["scenarios"]["agents"] = await scenario_agents(client)
        results["scenarios"]["cancellation"] = await scenario_cancel(client)
    finally:
        await client.close()
    return results


def sample_process(pid: int, seconds: float = 2.0) -> dict:
    try:
        import psutil
    except Exception:
        return {}
    try:
        process = psutil.Process(pid)
        process.cpu_percent(interval=None)
        time.sleep(seconds)
        return {
            "rss_mb": round(process.memory_info().rss / (1024 * 1024), 1),
            "cpu_percent": process.cpu_percent(interval=None),
        }
    except Exception:
        return {}


def seed_devices(count: int = 8) -> list[str]:
    """Tokens for the load generator's own devices, written to the same database the server uses."""
    import uuid

    from backend.core.security import get_service, hash_token, new_token, scopes_for_kind

    service = get_service()
    tokens = []
    for index in range(count):
        token = new_token()
        device_id = uuid.uuid4().hex[:12]
        kind = "windows" if index == 0 else "android"
        service.store.create_device(device_id, f"loadtest-{kind}-{index}", kind,
                                    scopes_for_kind(kind))
        service.store.add_token(device_id, hash_token(token))
        tokens.append(token)
    return tokens


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--json", help="write the report here")
    args = parser.parse_args()

    if args.serve:
        return serve(args.port)

    os.environ["MIMO_DATA_DIR"] = DATA_DIR
    os.environ.pop("MIMO_REQUIRE_AUTH", None)

    child = subprocess.Popen(
        [sys.executable, __file__, "--serve", "--port", str(args.port)],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=dict(os.environ),
    )
    try:
        line = child.stdout.readline().strip() if child.stdout else ""
        if line != "READY":
            print(f"server did not start: {line}", file=sys.stderr)
            return 2
        # Wait for the socket, then create a device in the same data directory.
        import httpx

        for _ in range(100):
            try:
                if httpx.get(f"http://127.0.0.1:{args.port}/health", timeout=1).status_code == 200:
                    break
            except Exception:
                time.sleep(0.1)
        tokens = seed_devices(9)
        report = asyncio.run(run(args.port, tokens[0], tokens[1:]))
        report["server"] = sample_process(child.pid)
        report["database_mb"] = round(
            sum(f.stat().st_size for f in Path(DATA_DIR).rglob("*.db*")) / (1024 * 1024), 2
        )
    finally:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()

    rendered = json.dumps(report, indent=2)
    if args.json:
        Path(args.json).write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
