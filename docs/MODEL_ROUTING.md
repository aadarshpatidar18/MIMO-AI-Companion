# Multi-model routing (Ollama + Gemini)

All model calls go through `backend/core/llm`. Providers sit behind one interface
(`LLMProvider.generate(request, model) -> LLMResponse`); the `ModelRouter` decides
which provider/model answers, retries, cools down and falls back.

## Setup
1. `pip install -r requirements.txt` (no new runtime packages; Gemini is called over REST with `requests`).
2. Optional cloud: create a key at https://aistudio.google.com/apikey and put it in `C:\MIMO\.env`
   (`GEMINI_API_KEY=...`) or set the environment variable. The key lives only on the PC.
3. Default selection is `ollama` (fully offline). Switch with `PUT /llm/selection`
   (`{"provider": "auto" | "gemini" | "ollama"}`) or `MIMO_LLM_PROVIDER`.

## Behaviour
| Selection | Result |
|---|---|
| `ollama` | Local only. Never contacts Google. |
| `gemini` | Gemini first for every non-local-only task; Ollama as fallback if `fallback_to_local` is true. |
| `auto` | Follows each task's route (default: chat/plan/summarize/research/code = Gemini then Ollama; intent = Ollama; memory = Ollama, local-only). |

* **Per-task models**: `PUT /llm/tasks/{task}` with ordered `targets` (`provider` + optional `model`), or `config/models.json`.
* **Per-call**: `LLMRequest(task=..., provider=..., model=..., allow_cloud=False)`.
* **Failures**: 429 -> exponential backoff + jitter, honouring Retry-After / `retryDelay` as a minimum.
  If the wait would exceed `max_total_wait` (15 s default) or the daily quota is exhausted, the router
  falls back immediately instead of blocking. A rate-limited, unavailable or auth-failed Gemini model
  is put on cooldown so later requests skip it. Ollama is never put on cooldown.
* **Usage**: every request actually sent is logged to `data/llm_usage.db` (counts, tokens, latency,
  outcome - never prompt text). `GET /llm/usage`. Optional self-imposed `rpm`/`rpd` limits in
  `config/models.json` block cloud calls before they hit Google.

## Things to verify yourself
* Free-tier quotas are per project and per model and change over time; they are only shown in
  Google AI Studio (rate-limit page). Set `limits` from what you see there. Nothing here assumes them.
* Free-tier eligibility of a given model (default `gemini-3.1-flash-lite`) - confirm in AI Studio.
* Google states that free-tier content may be used to improve its products. Hence: default is
  local-only, the `memory` task is `local_only`, and any request can pass `allow_cloud=False`.
  Do not route personal memory or screen contents to Gemini unless you accept that.

## Wiring (two lines in `backend/api.py`)
```python
from backend.core.llm.routes import router as llm_router
app.include_router(llm_router)
```
and in the existing agent/planner/`llm.py` replace the direct Ollama call with
`from backend.core.llm import generate_text` (`generate_text(prompt, system=..., task="plan")`).

## Android
No API key, Gemini URL or model SDK belongs in the app. It talks only to the backend.
`python scripts/check_no_secrets.py android` fails the build if a key pattern appears there.

## Not yet done
No streaming, no vision/image input, no auth on `/llm/*` (Phase 9), no TPM limit.
