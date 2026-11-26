# Operators — what MIMO can do to a machine

Everything here is a real tool in the agent registry: the planner can choose it, the policy decides
whether to ask first, and the engine records the result. Levels: **1** read-only, **2** reversible,
**3** always confirmed with you before it runs.

## Files (level 1–3)

| Tool | Level | Does |
|---|---|---|
| `list_files` | 1 | List a folder: name, type, size |
| `read_file` | 1 | Read text or PDF (PDF needs the optional `pypdf`) |
| `search_files` | 1 | Find files by name |
| `write_file` | 2 | Create a text file; replacing one needs `overwrite: true` |
| `create_folder` | 2 | Make a folder |
| `move_path` | 3 | Move or rename |
| `delete_path` | 3 | Delete one file or an empty folder — never recursive |

**The sandbox is the whole safety story.** No tool takes a path that is not first resolved and
proven inside an allowed root. `..` traversal and symlinks are resolved *before* the check, so a
shortcut cannot smuggle you out. Roots come from `MIMO_FILE_ROOTS` (several allowed, separated by
`;` on Windows, `:` elsewhere). Defaults: `Documents`, `Downloads`, `Desktop`, `Projects`,
`Documents/MIMO`, and your home folder.

## System (level 1/3)

* `system_info` (1) — OS, CPU, memory, disk, Python.
* `run_powershell` (1) — **one approved cmdlet**, named separately from its arguments:
  `Get-Process`, `Get-Service`, `Get-Date`, `Get-ComputerInfo`, `Get-ChildItem`, `Get-NetIPAddress`,
  `Get-Volume`. There is no free-form command string, so there is nothing to escape.
* `run_command` (3) — an allowlisted program (`python`, `pytest`, `npm`, `node`, `git`, `gradle`,
  `java`, `pip`, `uvicorn`, `adb`) with separate arguments, inside an allowed folder, with a timeout.
* `run_tests` (3) — runs pytest in a project folder and returns the summary line and the output.

Every one of these runs as a child process in its own process group with a hard timeout, and the
group is killed if it overruns. The agent engine cannot kill a thread; this is how a hung command
still stops.

## Applications (level 2/3)

`launch_app` (2), `close_app` (3), `list_windows` (1). Aliases: `notepad`, `calculator`, `explorer`,
`terminal`, `powershell`, `browser`, `vscode`, `android studio`, `chrome`, `spotify`. Teach it your
own in `config/apps.json` (copy `config/apps.example.json`); values are argv lists, never shell
strings.

## Screen and computer control (level 2/3)

`capture_screen` (2), `read_screen_text` (1, OCR), `type_text` (3), `press_keys` (3), `click_at` (3),
`scroll` (2). These need optional packages and a real display: `pillow` (capture on Windows,
`mss` elsewhere), `pytesseract` + the Tesseract program (OCR), `pyautogui` (input). `FAILSAFE` is on:
slamming the mouse into a screen corner aborts a run.

Screenshots are written into your allowed folders only. OCR text never leaves the machine.

## Browser (level 1–3)

A real Playwright session (one worker thread owns it) with these tools:

| Tool | Level | Does |
|---|---|---|
| `browser_open` | 2 | Open a page, return title and opening text |
| `browser_read` | 1 | Read the current page, or a URL |
| `browser_search` | 1 | Search DuckDuckGo, Google, Bing or YouTube and list results |
| `browser_click` | 2 | Follow a link or press a harmless control |
| `browser_click_action` | 3 | Press something consequential — always confirmed |
| `browser_screenshot` | 2 | Screenshot the page |
| `browser_where` | 1 | Which page is it on |
| `browser_close` | 2 | Close the session |

Two guards are enforced in code, not just in the prompt:

1. **URLs** must be `http`/`https`; `file:`, `javascript:` and other schemes are refused.
2. **A click whose target reads like money, messaging, deletion or an account change**
   (*subscribe, buy, pay, send, delete, sign up, …*) is refused by `browser_click` with a message
   telling the caller to use `browser_click_action`, which the policy always confirms with you.

MIMO does not bypass CAPTCHAs, does not type passwords, and does not automate sign-in. A site that
needs you to log in is a step only you can take.

## What is not built

* Windows UI Automation by control name (the stronger alternative to coordinates).
* Organising a folder in bulk ("tidy my downloads") as one approved plan.
* Persistent browser profiles, so logins do not survive a restart.
* Android device operators — see the roadmap.

## Checking what this machine supports

`GET /system/capabilities` reports it, and the same data is what the UI can show:

```json
{"platform":"Windows","files":true,"file_roots":["C:\\Users\\you\\Documents"],
 "shell":true,"screenshot":true,"ocr":false,"input":true,"windows":true,"apps":true}
```
