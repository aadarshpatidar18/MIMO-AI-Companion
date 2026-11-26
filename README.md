# MIMO – Personal AI Companion

**MIMO** is a personal AI companion designed to bring together conversational AI, persistent memory, and Android integration.

The project combines a locally running Large Language Model (LLM), a Python-based backend, SQLite memory storage, and an Android application built using Kotlin and Jetpack Compose.

The long-term vision is to develop MIMO into an intelligent personal assistant capable of understanding user context, remembering preferences, planning tasks, and interacting with Android applications with appropriate user authorization.

---

## Current Features

- **One interface, every screen:** a responsive web app served by the backend at `/`. Chat,
  history, memory, devices, agent activity and settings on the laptop and in a phone browser.
- **MIMO's character:** name, warmth, humour and verbosity are yours to set, and the same settings
  shape every answer (`backend/core/persona.py`).
- **Provider-independent models:** Ollama locally, Gemini in the cloud, with retry, cooldown,
  fallback, usage tracking and per-task routing. Personal memory stays on the machine unless you
  opt in.
- **Durable, shared conversations:** SQLite-backed history that survives a restart and is readable
  from every paired device.
- **Device identity:** pairing codes, hashed bearer tokens, per-device scopes, revocation and an
  audit trail.
- **Agent engine:** plan → policy → execute → verify → replan, with autonomy levels, background
  tasks, cancellation, confirmations, timeouts and restart recovery.
- **Persistent memory:** interests, skills, goals, preferences and projects, searchable, editable
  and deletable from the app.
- **Operators:** file management inside a sandbox, approved PowerShell, allowlisted dev commands,
  application launch/close, screenshots and OCR, mouse and keyboard, and a real Playwright browser
  that searches, reads and — with your approval — clicks (`docs/OPERATORS.md`).
- **Voice:** speak to MIMO and have it answer aloud in the browser interface; local whisper is the
  planned upgrade.
- **Android client:** Kotlin/Compose chat app (chat only for now).

Setup: `docs/INSTALL.md`. Interface: `docs/UI.md`. Operators: `docs/OPERATORS.md`.

## System Architecture

```text
                 ANDROID APPLICATION
                 Kotlin + Jetpack Compose
                          |
                          |
                     HTTP / JSON
                          |
                          v
                    FASTAPI BACKEND
                          |
                          v
                     MIMO AGENT
                          |
             +------------+------------+
             |            |            |
             v            v            v
          LLM ENGINE    MEMORY       TOOLS
             |            |            |
             v            v            v
          Ollama       SQLite      Tool Registry
             |
             v
        Qwen 2.5 1.5B
```

### Technology Stack

| Component | Technology |
|---|---|
| Android Application | Kotlin |
| UI Framework | Jetpack Compose |
| Backend | Python |
| API Framework | FastAPI |
| LLM Runtime | Ollama |
| Language Model | Qwen 2.5 1.5B |
| Database | SQLite |
| Communication | HTTP / JSON |
| Version Control | Git / GitHub |

## Project Structure

```text
MIMO/
│
├── android/
│   ├── app/
│   │   └── src/
│   │       └── main/
│   │           ├── java/
│   │           │   └── com/mimo/companion/
│   │           │       ├── MainActivity.kt
│   │           │       └── ui/theme/
│   │           └── AndroidManifest.xml
│   │
│   └── gradle/
│
├── backend/
│   ├── main.py
│   ├── api.py
│   ├── llm.py
│   ├── planner.py
│   ├── agent.py
│   ├── tools.py
│   ├── memory.py
│   ├── database.py
│   └── cleanup.py
│
├── requirements.txt
├── README.md
└── .gitignore
```

## Getting Started

### Prerequisites

- Python 3.10 or later
- Android Studio
- Android SDK
- Ollama
- Git
- Java Development Kit compatible with the Android Gradle project

### 1. Clone the Repository

```bash
git clone https://github.com/aadarshpatidar18/MIMO-AI-Companion.git
cd MIMO-AI-Companion
```

### 2. Set Up Python Environment

```bash
python -m venv venv
```

Activate the environment on Windows Git Bash:

```bash
source venv/Scripts/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

### 3. Set Up Local LLM

Install Ollama and download the model:

```bash
ollama pull qwen2.5:1.5b
```

Make sure Ollama is running locally.

### 4. Start the Backend

From the project root:

```bash
uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload
```

Backend health check:

```text
http://127.0.0.1:8000/health
```

API documentation:

```text
http://127.0.0.1:8000/docs
```

### 5. Run the Android Application

1. Open the `android` directory in Android Studio.
2. Allow Gradle synchronization to finish.
3. Connect an Android device or start an emulator.
4. Configure the backend address in the Android API service.
5. Build and run the application.

For an Android Studio emulator, the host machine is generally accessible through:

```text
http://10.0.2.2:8000
```

For a physical Android device, use your development machine's local network IP address. Both devices must be connected to an accessible network.

**Note:** The current development configuration uses HTTP. Do not expose the development backend publicly. Production deployment requires authentication, secure communication, and appropriate access controls.

## Model Providers

MIMO routes every model call through `backend/core/llm`. By default it runs fully offline on Ollama.
To enable Google Gemini (optional), copy `.env.example` to `.env`, set `GEMINI_API_KEY`, then choose
`auto` or `gemini` via `PUT /llm/selection`. Gemini failures and rate limits fall back to Ollama
automatically. Personal memories are never sent to a cloud model unless `MIMO_ALLOW_MEMORY_TO_CLOUD=true`.
See `docs/MODEL_ROUTING.md` and `docs/AUDIT.md`.

## The interface

Start the backend and open <http://127.0.0.1:8000> — MIMO's own interface, the same one on your
laptop and your phone browser. Chat, conversation history, memory, devices and permissions, agent
activity with a Stop button, and MIMO's character (name, warmth, humour, how much it says) all live
there. Pairing happens in the app: `python -m backend.main pair` on the PC prints a code, you type it
once on the phone, and both devices share one history from then on.

`docs/UI.md` describes the screens and what is wired to what.

## Devices, identity and shared conversations

MIMO is one brain for several screens. A device pairs once with a short code shown on the PC,
receives a bearer token (only its SHA-256 hash is stored), and from then on reads and writes the
same conversations as every other device.

```bash
python -m backend.main pair       # prints a code on the PC (backend must be running)
python -m backend.main devices    # what is paired, and when each was last seen
```

`POST /chat` with a `conversation_id` uses the shared, durable history; without one it keeps the
older in-memory behaviour. Full endpoint and scope reference: `docs/DEVICES_AND_CONVERSATIONS.md`.
Set `MIMO_REQUIRE_AUTH=1` once your PC is paired to require a token on every route.

Run the tests: `pip install -r requirements-dev.txt && pytest`.
Terminal chat: `python -m backend.main` (from the project root).

## Development Roadmap

| Feature | Status |
|---|---|
| Python backend | Completed |
| FastAPI integration | Completed |
| Local LLM integration | Completed |
| SQLite persistent memory | Completed |
| Basic tool execution | Completed |
| Android chat interface | Completed |
| Android-backend communication | Completed prototype |
| Conversation history improvements | Planned |
| Voice interaction | Planned |
| Text-to-Speech | Planned |
| Virtual pet interface | Planned |
| Advanced memory and personalization | Planned |
| Android app interaction | Planned |
| Screen understanding and OCR | Planned |
| Agent planning and task verification | Planned |
| Production security and deployment | Planned |

## Project Vision

MIMO is being developed as a learning-by-building project exploring the intersection of:

- Artificial Intelligence
- Agentic AI
- Large Language Models
- Android Development
- Human-Computer Interaction
- Persistent Memory Systems
- Robotics-inspired autonomous systems

The ultimate goal is to build an AI companion that can understand context, remember information, reason about tasks, and assist users across their digital environment.

## Author

**Aadarsh Patidar**

Materials Science and Metallurgical Engineering  
Indian Institute of Technology Hyderabad

---

*Built with curiosity, experimentation, and a passion for intelligent systems.*