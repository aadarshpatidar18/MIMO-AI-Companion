# Source reconciliation report — ZIP vs GitHub

Date: 2026-11-27. Author: Spark (lead engineer on MIMO).

## Verdict

**The two sources are identical. There is nothing to merge.**

The supplied `MIMO-AI-Companion-main.zip` (314,208 bytes, 143 files) is a byte-for-byte
copy of `github.com/aadarshpatidar18/MIMO-AI-Companion` at `main` =
`59c2c256cfd8b55a154606a7414549f8167ce6c5` ("feat(memory): importance, ranked FTS5 recall,
correction, in-place migration", 2026-11-26).

Consequences, all of which the brief anticipated as worst cases and none of which apply:

- No file exists only in the ZIP.
- No file exists only in GitHub.
- No conflicting versions.
- No unpushed work to rescue.
- No risk of overwriting newer code with older ZIP contents, or the reverse.

## How this was established (reproducible)

```
git clone https://github.com/aadarshpatidar18/MIMO-AI-Companion.git     # succeeds
cd MIMO-AI-Companion && git rev-parse HEAD
# 59c2c256cfd8b55a154606a7414549f8167ce6c5
unzip MIMO-AI-Companion-main.zip -d zip/
diff -rq zip/MIMO-AI-Companion-main . --exclude=.git
# (no output — identical)
git ls-files | wc -l          # 143
find zip/MIMO-AI-Companion-main -type f | wc -l   # 143
git status --short            # clean (the only extra path, data/, is a gitignored test artifact)
```

Branches on the remote: `main` and `mimo/v1` (`a5b4228` plus merge `1627ea3`), both already
contained in `main`. Git history is intact and is preserved; no history rewriting was needed.

## Baseline re-verified in this environment

Python 3.12.3, Linux, `pip install -r requirements.txt -r requirements-dev.txt`, then:

```
python -m pytest backend/tests -q
302 passed, 1 skipped  (7.5s)
```

The one skip is `test_browser_live.py`, skipped because `playwright` is not installed in
this container (`pip install -r requirements-optional.txt` + `playwright install chromium`
enables it).

**The historical claim of "307 tests" is not reproducible as stated**: the suite at this
commit collects 303 tests (302 pass, 1 skips for a missing optional dependency). The
number 307 in `docs/PROJECT_PLAN.md` §6e counted 307 across an earlier tree and is
corrected here. No test is deleted to make a number match; the honest baseline is
**302 passing, 1 skipped, 0 failing**.

## Branch for continuing work

`mimo/v2-continuation`, created from `59c2c25`. `main` stays green and untouched until a
module is finished and its suite passes; modules merge in and `main` remains the release
source of truth.

## What the brief calls "remaining work" vs what is actually left

The brief's architecture section is accurate — the backend is at the stated level. The
remaining-work list matches the real gap, with these corrections:

| Brief says | Actual state |
|---|---|
| 307 tests pass | 302 pass, 1 skipped — corrected above |
| Android app exists | It is a **chat-only** Compose client (~695 Kotlin lines, hardcoded base URL). No Room, no pairing UI, no notifications, no accessibility service, no APK ever built. |
| Voice implemented | Browser Web Speech API only (speech in/out via the browser). No local Whisper, no Kokoro; nothing runs offline. |
| Windows desktop shell | Does not exist. |
| Load/performance testing | Does not exist. |
| Packaging | Docs only (`docs/INSTALL.md`); no installer, no APK, no signing config. |
| Windows/Android automation | Code exists for Windows (PowerShell allowlist, screen, input) and is tested through mocks/Linux; **never executed on Windows or a phone**. |

Nothing from either source was discarded; this report adds evidence rather than replacing
code.
