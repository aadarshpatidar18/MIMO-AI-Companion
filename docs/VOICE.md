# Voice — local speech in and out

Date: 2026-11-27. Branch: `mimo/v2-continuation`.

Speech recognition is `faster-whisper` (CTranslate2) on your machine; speech synthesis is
Kokoro-82M through `kokoro-onnx`. Neither is required for the backend to start, and neither sends
audio anywhere unless you explicitly switch to a cloud provider *and* allow it.

## How it is put together

```
backend/core/voice/
  config.py     VoiceSettings — one JSON file (~/.mimo/voice.json), validated on every save
  base.py       Transcript / AudioChunk / STTEngine / TTSEngine / Null engines / sentence chunking
  stt_local.py  WhisperSTT: lazy load, device+compute selection, stdlib WAV decode, RTF
  tts_local.py  KokoroTTS: lazy load, sentence streaming, real cancel between chunks
  cloud.py      opt-in provider adapters (registered, not hard-wired to a vendor)
  manager.py    VoiceManager: resolves engines, reports status, benchmark
  routes.py     /voice/status, /voice/settings, /voice/transcribe, /voice/speak, /voice/cancel
```

Decisions worth knowing:

- **Lazy everything.** `import backend.core.voice` pulls no model library. A missing package makes
  the *request* fail with an install instruction, never the API start. Tested by importing the
  package with numpy, faster-whisper, kokoro, ctranslate2 and onnxruntime all blocked.
- **WAV is decoded with the standard library**, not faster-whisper's own decoder. That decoder goes
  through PyAV, whose API drifts (`av.open(metadata_errors=…)` was removed in a recent release and
  broke it outright here). Every recording this project receives is a 16 kHz mono WAV, so a stdlib
  decode plus linear resampling is both fewer dependencies and deterministic.
- **Cloud needs two switches.** `stt_provider: "cloud"` *and* `allow_cloud: true`, plus an API key.
  With the provider chosen but not allowed, the manager refuses and says which switch is missing.
- **Cancel is real.** `KokoroTTS.cancel()` trips a flag that the sentence generator checks between
  chunks, so a barge-in drops the rest of the reply instead of finishing the paragraph.
- **Kokoro language codes are mapped.** Kokoro's phonemiser rejects `en`; the manager maps a bare
  two-letter code to the model's own tag (`en` → `en-us`) and turns any remaining phonemiser error
  into a settings message naming `tts_voice` and `language`.

## Install

```
pip install faster-whisper kokoro-onnx numpy
mkdir -p ~/.mimo/models
# Kokoro model files (311 MB + 27 MB), from the kokoro-onnx releases:
curl -L -o ~/.mimo/models/kokoro-v1.0.onnx \
  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -L -o ~/.mimo/models/voices-v1.0.bin \
  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```

The Whisper model downloads itself on first use into `~/.mimo/models`. `small.en` int8 is about
480 MB on disk and ~0.8 GB resident while loaded.

## Measured performance (real numbers, this container)

Environment: Python 3.12.3, Linux x86-64, **4 CPU cores, 7 GB RAM, no GPU**. Weights:
`faster-whisper small.en` int8, Kokoro `v1.0` ONNX with `af_heart`.
Reproduce with `python scripts/bench_voice.py --roundtrip --json`.

| Measurement | Result |
|---|---|
| STT cold start (load + first 2.67 s clip) | 2338 ms |
| STT warm, 2.67 s clip | 1194–1280 ms → **RTF 0.45–0.48** (~2.2× faster than real time) |
| STT resident memory after load | +792 MB RSS |
| TTS first chunk, cold (44 chars) | 1660 ms, 125 KiB of WAV |
| TTS warm, short sentence (16 chars) | ~400 ms for 1.09 s of audio (RTF ≈ 0.37) |
| TTS warm, 170 chars in 3 streamed sentences | first chunk **1718 ms**, all three by 3429 ms |
| TTS resident memory after load | +454 MB RSS |
| Round trip (say it, hear it, transcribe what was said) | text came back exactly: *"The quick brown fox jumps over the lazy dog."* |

What those numbers mean for use:

- **Conversation is viable.** A one-sentence answer starts playing in under half a second once the
  models are warm; a two-second question transcribes in about a second.
- **Memory is the real cost, not speed.** Whisper small.en and Kokoro together are roughly 1.25 GB
  resident. On a 16 GB laptop that is acceptable; on an 8 GB machine with a browser open, use
  `base.en` (≈150 MB) or let the phone do voice with its own engines (which the Android app does).
- **Cold start is the worst case** — 4 seconds before the first sound if nothing is warm. The
  manager is meant to be warmed once at startup, not per request.

**Not measured:** any GPU, Windows, or the target laptop. The `small.en` choice is justified by the
numbers above on 4 CPU cores, not by a benchmark on Aadarsh's PC; `large-v3` was not downloaded
because it would not fit this container's memory alongside the rest of the suite.

## API

| Route | Purpose |
|---|---|
| `GET /voice/status` | What is actually installed and ready, with the reason when it is not |
| `GET`/`PUT /voice/settings` | Read or change the settings (partial body allowed); 400 names the bad field |
| `POST /voice/transcribe` | Raw WAV body (`audio/wav`), returns text, language, duration, RTF, segments |
| `POST /voice/speak` | `{"text": "…", "speed": 1.0}` → `audio/wav` bytes, or 503 with the reason |
| `POST /voice/cancel` | Stops the next chunk of a streaming reply |

Audio-in uses a raw body rather than multipart on purpose: it needs one dependency fewer
(`python-multipart`), and any client that can record can post bytes. Requests over 12 MB are
refused before a model runs.

## Where voice runs, and why not on the phone

The phone uses Android's own recogniser and TTS (`voice/VoiceController.kt`): they are already
installed, work offline on modern Android, and cost no download. Shipping a 480 MB Whisper model and
a 310 MB Kokoro model to a phone for a push-to-talk button would cost battery, storage and startup
time for a worse experience than the platform engine. The heavy stack belongs on the machine with
the RAM and the microphone array — that is this one.

## Tests

`backend/tests/test_voice.py` — 35 tests, none of which need a model installed:

- settings defaults, cloud double-gating, per-field validation, round trip, corrupt file
- sentence chunking for streaming (splits, long-sentence cut, empty input)
- refusal messages that name the missing package or file, and the 503 shapes at the routes
- `415` wrong content type, `400` empty body, `413` oversize before any model runs
- cancel reporting, `AudioChunk` format, RTF arithmetic, and the "no numpy needed to import" guard

The round-trip benchmark above is what proves the engines work; the suite proves the refusals are
honest.
