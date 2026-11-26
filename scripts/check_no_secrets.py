"""Fail if API keys or Gemini endpoints appear in the Android sources.

The Android app must only talk to the MIMO backend; all cloud keys live in the
backend's environment. Usage: python scripts/check_no_secrets.py [android_dir]
"""
import re
import sys
from pathlib import Path

PATTERNS = {
    "Google API key": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "AI Studio auth key": re.compile(r"\bAQ\.[0-9A-Za-z_\-]{20,}"),
    "Gemini env var / endpoint": re.compile(r"GEMINI_API_KEY|GOOGLE_API_KEY|generativelanguage\.googleapis\.com"),
}
SKIP_DIRS = {"build", ".gradle", ".idea", ".git"}
EXTS = {".kt", ".java", ".xml", ".kts", ".gradle", ".properties", ".json", ".toml", ".txt", ".md"}


def main(root: Path) -> int:
    bad = []
    files = 0
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix not in EXTS or SKIP_DIRS & set(p.parts):
            continue
        files += 1
        text = p.read_text(encoding="utf-8", errors="ignore")
        for label, rx in PATTERNS.items():
            for m in rx.finditer(text):
                bad.append(f"{p}:{text[:m.start()].count(chr(10)) + 1}: {label}")
    print(f"scanned {files} files under {root}")
    for b in bad:
        print("FOUND", b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "android")))
