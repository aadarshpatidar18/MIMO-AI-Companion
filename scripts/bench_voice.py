"""Measure the voice engines that are actually installed on this machine.

    python scripts/bench_voice.py --roundtrip
    python scripts/bench_voice.py --audio recording.wav
    python scripts/bench_voice.py --text "A sentence to speak" --write-wav out.wav

Exit code 2 means "a model is missing", with the reason on stderr — never a table of made-up
numbers. Everything printed here was measured in this process.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.voice import VoiceManager, VoiceUnavailable, load_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", help="a WAV file to transcribe")
    parser.add_argument("--text", default="The quick brown fox jumps over the lazy dog.",
                        help="text to synthesise")
    parser.add_argument("--roundtrip", action="store_true",
                        help="synthesise the text, then transcribe it")
    parser.add_argument("--write-wav", help="write the synthesised audio here")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--model-dir", help="override the model directory")
    args = parser.parse_args()

    settings = load_settings()
    if args.model_dir:
        settings.model_dir = args.model_dir
    manager = VoiceManager(settings)

    audio_path = args.audio
    result: dict = {}

    if args.roundtrip or not args.audio:
        try:
            result["tts"] = manager.bench(text=args.text)["tts"]
            chunk = manager.speak(args.text)
        except VoiceUnavailable as error:
            print(f"tts unavailable: {error}", file=sys.stderr)
            return 2
        target = Path(args.write_wav or "/tmp/mimo-bench.wav")
        target.write_bytes(chunk.audio)
        audio_path = str(target)
        result["tts"]["wav"] = str(target)
        result["tts"]["wav_bytes"] = len(chunk.audio)

    if audio_path:
        try:
            measured = manager.bench(audio_path=audio_path)
            result.setdefault("environment", measured["environment"])
            result["stt"] = measured["stt"]
        except VoiceUnavailable as error:
            print(f"stt unavailable: {error}", file=sys.stderr)
            return 2

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        env = result.get("environment", {})
        print(f"environment: python {env.get('python')} · {env.get('platform')} · "
              f"{env.get('cpu_count')} CPUs")
        if "tts" in result:
            tts = result["tts"]
            print(f"tts  {tts['engine']}: first chunk {tts['first_chunk_ms']} ms, "
                  f"total {tts['total_ms']} ms for {tts['text_chars']} chars, "
                  f"{tts['audio_bytes'] / 1024:.0f} KiB, rss +{tts['rss_delta_mb']} MB")
        if "stt" in result:
            stt = result["stt"]
            print(f"stt  {stt['engine']}: {stt['audio_s']} s audio in {stt['inference_ms']} ms "
                  f"(load+inference {stt['load_plus_inference_ms']} ms), "
                  f"RTF {stt['real_time_factor']}, rss +{stt['rss_delta_mb']} MB")
            print(f"     heard: {stt['text']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
