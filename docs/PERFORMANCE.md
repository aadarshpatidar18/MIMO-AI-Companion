# Performance and resilience — measured, not estimated

Date: 2026-11-27. Reproduce: `python scripts/load_test.py --json report.json`.

## What this measures, and what it deliberately does not

The language model is replaced by a fake provider that answers instantly. That isolates what
**MIMO itself** costs — HTTP, SQLite, the conversation store, memory search, the agent engine, the
rate limiter and the policy layer — from the speed of whichever model is installed. Model latency is
a separate question with its own numbers in `docs/VOICE.md` and `docs/MODEL_ROUTING.md`. Adding a
model to this run would produce a big number that says nothing about MIMO's own overhead.

**Environment:** Python 3.12.3, Linux x86-64, 4 vCPU, 7 GB RAM, containerised, single uvicorn
worker, SQLite in WAL mode. The server runs in its own process; RSS and CPU are read from that
process with psutil.

## Results

| Scenario | Result |
|---|---|
| 40 sequential chat turns, one device | p50 **4.2 ms**, p95 7.6 ms, p99 10.0 ms → **230 turns/s** |
| 90 turns, 9 devices in parallel | p50 **35.2 ms**, p95 53.4 ms, p99 65.9 ms → **241 turns/s**, 0 rejections |
| Conversation with 200 stored messages: read all | 4.1 ms |
| Same conversation: one more turn (10 messages of history) | 4.6 ms |
| Memory search, 300 facts, 20 queries | p50 **4.9 ms**, p95 8.0 ms |
| 30 requests with a bad token | 30 × 401, p50 1.9 ms — rejected before any work |
| 20 identical turns posted at once from one device | 9 × 200, 11 × 429 (the 60-turns-per-minute per-device limit, partly used by earlier scenarios), **18 messages stored, 18 unique ids** — nothing lost, nothing duplicated |
| 8 agent goals submitted at once | 8/8 succeeded in 0.2 s, 0 left unfinished |
| Cancel a running agent task | stop acknowledged in 19.9 ms |
| Server process after the whole run | **RSS 71.5 MB**, 1.0 % CPU, database 7.09 MB |

Re-measured after the V1.0 review added a per-conversation turn lock and body-size middleware;
the lock serialises turns *within* one conversation and costs nothing measurable across
conversations (p50 4.2 ms sequential, 35.2 ms at nine devices).

Reading these honestly:

- **MIMO's own overhead is small.** At p95 under 10 ms sequentially, the wall-clock a person feels
  is the model, not the plumbing. The 28 ms p50 added under 9-way concurrency is thread
  contention on the SQLite write path, not a queue: throughput still rose (178 → 225 turns/s).
- **The rate limiter is the first thing that bites**, and it is meant to: 60 turns per minute per
  device. Nine devices in parallel produced no refusals at all; one device that had already spent
  its window got 429s. That is the right shape for a personal system with a handful of devices — a
  per-device limit rather than a global one, so one noisy client cannot lock out the others
  (`test_resilience.py::test_one_noisy_device_cannot_lock_another_out`).
- **Duplicate protection works at the storage layer.** Eighteen stored messages for nine accepted
  turns, all with unique ids, means each accepted turn wrote exactly its question and its answer.
  Eleven requests were refused before storing anything.
- **Memory search stays flat** because FTS5 does the ranking: 300 facts and 6 ms, not a linear
  scan.
- **Cancellation on an instant fake plan is not a real test of cancellation** — the task had already
  succeeded. The genuine case (a long tool step) is covered by
  `backend/tests/test_agent_engine.py`, which kills a real subprocess mid-run.

## What the suite already covers, beyond this run

Rather than duplicate them here, these live in the existing suite and are the reason the numbers
above can be trusted:

| Concern | Test |
|---|---|
| Concurrent appends keep every message and unique ids | `test_conversations.py::test_concurrent_appends_keep_every_message_and_unique_ids` |
| A turn is stored whole or not at all | `test_conversations.py::test_a_turn_is_stored_whole_or_not_at_all` |
| Provider failure and recovery | `test_llm_retry_usage.py`, `test_llm_router.py` |
| Agent timeouts, cancellation, loop prevention | `test_agent_engine.py` |
| Policy refusal before a side effect | `test_dispatch_policy.py` |
| Restart durability of conversations | `test_conversations.py::test_messages_survive_reopening_the_database` |
| Auth gate closes everything but health and pairing | `test_security.py::test_auth_gate_closes_everything_but_health_and_pairing` |

## Bottlenecks, named

1. **The model.** Everything else is single-digit milliseconds. On this machine a local voice turn
   costs ~1.2 s of Whisper and 0.4–1.7 s of Kokoro before the chat turn even starts.
2. **One uvicorn worker.** SQLite plus a single worker is right for a personal system and wrong for
   a crowd; measured throughput of ~225 turns/s is roughly 40× what one person can type.
3. **SQLite write lock under parallel writers.** Visible as p50 rising 5 → 38 ms at 9 devices. If
   this ever mattered, the fix is a write queue, not a different database.
4. **Notification polling on the phone** (20 s interval) is a phone-side cost, not a server one:
   one small `GET /agent/tasks` per device per 20 s.

## Not measured here

- Windows (the target machine), GPU inference, and any real LLM. Those need the laptop.
- An Android device under real network conditions; the app's offline queue is tested only by unit
  tests and the manual checklist in `docs/ANDROID_OPERATOR.md`.
- Multi-hour soak. The run above is minutes, not hours, and says nothing about leak behaviour over
  a day.
