# MIMO — technology decisions (Week 1)

Source: `docs/RESEARCH_W1.md` (Gemini, 2026-11-26). Each entry records the choice, why,
the evidence it rests on, and the gate that must pass before it is called done. A decision
marked **adopted** is a design commitment; a decision marked **pending hardware** is the
default we code against but cannot verify without Aadarsh's PC or phone.

## D1 — Local models for `plan` and `chat` (adopted; benchmark gate)

| Route | Model | Quant | Licence | Notes |
|---|---|---|---|---|
| `plan` | `qwen3:4b` | Q4_K_M (~2.5 GB) | Apache-2.0 | Ollama `format` JSON schema, `think: false` |
| `chat` | `qwen3:1.7b` | Q4_K_M (~1.4 GB) | Apache-2.0 | share `qwen3:4b` if model-swap stutter is worse than the quality drop |
| `intent`, `memory` | unchanged (`qwen2.5:1.5b`, local-only) | | | small classification task; revisit only if errors show up |

Why: `qwen3:4b` leads the sub-7B class on BFCL v4 tool calling and leaves ~4 GB of 8 GB VRAM
for STT/TTS. 4-bit quantisation costs ~10 points on strict tool accuracy, so `plan` must always
use grammar-constrained JSON, never prompt-only JSON.

Gate: 20-prompt MIMO plan fixture on the target laptop — `qwen3:4b` must beat `qwen2.5:1.5b`
on schema-valid, semantically-correct plans before the default is switched in `config/models.json`
(the example config is documentation, not runtime).

## D2 — Speech to text (adopted; hardware gate)

`faster-whisper` (MIT), `large-v3-turbo` INT8/FP16 on GPU, `small.en` INT8 on CPU. Wake word is
`openWakeWord` (Apache-2.0) on CPU; endpointing and barge-in is `silero-vad` (MIT).
Never run Whisper in an always-on loop — it burns GPU and hallucinates on silence.

Gate: measure time-to-first-partial and barge-in cut latency on the target laptop; if the GPU is
AMD/Intel, CTranslate2 falls back to CPU and `whisper.cpp` with Vulkan becomes the better path.

## D3 — Text to speech (adopted)

`Kokoro-82M` via `kokoro-onnx` (Apache-2.0, ~300 MB), sentence-level streaming, playback
abortable mid-chunk for barge-in. **Piper is rejected as the default**: the maintained successor
`OHF-Voice/piper1-gpl` is GPL-3.0 (espeak-ng), a copyleft constraint we should not take on for a
closed personal product; it also sounds flatter. Piper remains a fallback (subprocess) only if
Kokoro latency disappoints.

## D4 — Android automation (adopted; on-device gate)

Sideloaded personal-use app: `AccessibilityService` (`canRetrieveWindowContent`,
`canPerformGestures`, `isAccessibilityTool="true"`) for reading screen text and tapping labelled
nodes, plus standard `Intent`s for structured actions. One-time manual
Settings → Apps → MIMO → ⋮ → "Allow restricted settings" unlock after install; Play Store is
not a distribution path (policy rejects general-purpose accessibility agents).

Hard limits we accept: `FLAG_SECURE` screens, `accessibilityDataSensitive` views, Canvas UIs with
no semantics. Manual tests needed on the actual phone: OEM background killing, sensitive-view
node visibility, WebView/Compose trees, background activity launch from the backend.
MIMO must stay fully usable with automation permissions off (chat, history, memory, voice).

## D5 — Memory search (adopted; eval gate)

Ship SQLite FTS5 (BM25) alone. It is 1–5 ms at 10³–10⁴ entries; `sqlite-vec` is ~3–50 ms at that
scale, so latency is never the reason to add it. Add hybrid FTS5 + `sqlite-vec` RRF only when a
personal 50–100 query eval shows FTS5 Recall@5 below 80% on paraphrase queries — typically past
~2,000–5,000 varied entries. Build the eval harness with the Milestone 3 memory work so the
threshold is measurable rather than guessed.

## Consequences for the roadmap

- Milestone 3 (memory) grows by one item: the recall eval set that governs D5.
- Milestone 6 (Android) starts with a throwaway probe APK to test D4's four on-device unknowns
  before the operator is designed around them.
- Milestone 7 (voice) is `faster-whisper` + Kokoro behind one `VoiceService` interface, so a
  Piper or whisper.cpp backend can be swapped in without touching callers.
- Model defaults are changed in `config/models.json` only after D1's benchmark; until then the
  example config keeps the current default and points at this file.
