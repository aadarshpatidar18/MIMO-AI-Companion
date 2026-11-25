# MIMO – Personal AI Companion

**MIMO** is a personal AI companion designed to bring together conversational AI, persistent memory, and Android integration.

The project combines a locally running Large Language Model (LLM), a Python-based backend, SQLite memory storage, and an Android application built using Kotlin and Jetpack Compose.

The long-term vision is to develop MIMO into an intelligent personal assistant capable of understanding user context, remembering preferences, planning tasks, and interacting with Android applications with appropriate user authorization.

---

## Current Features

- **Conversational AI:** Interact with MIMO through an Android chat interface.
- **Local LLM:** Uses Ollama with Qwen 2.5 (1.5B) for local inference.
- **Persistent Memory:** Stores user interests, skills, goals, preferences, and projects using SQLite.
- **Memory Retrieval:** Retrieves stored information based on user queries.
- **Memory Management:** Supports saving, searching, updating, and forgetting memories.
- **REST API:** FastAPI connects the Android application to the AI backend.
- **Android Integration:** Native Android application built using Kotlin and Jetpack Compose.
- **Basic Tool Execution:** Supports selected operations such as calculations, date/time retrieval, and opening allowlisted websites.

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