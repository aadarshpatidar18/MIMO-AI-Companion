"""Launch the desktop shell from a checkout:  python desktop/run.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mimo_desktop.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
