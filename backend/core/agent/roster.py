"""The agent roster: named specialists with their own tools, ceiling and model route.

The orchestrator is deliberately simple and legible: a goal is matched to one specialist, that
specialist plans with only its own tools, and the engine runs it under the same policy and
verification as any other task. A goal that matches nobody goes to the generalist, which is the
whole registry - so nothing that used to work stops working.

Three roles from the brief are deliberately not here: Communication needs transports that do not
exist yet, Verification is already what the engine does to every step, and Planning is the planner
itself. Inventing agents with no tools would be theatre; `RESERVED` records the decision instead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

from .engine import AgentEngine
from .planner import AgentPlanner
from .policy import AutonomyPolicy
from .registry import READ_ONLY, ToolRegistry

RESERVED = {
    "communication": "needs email/chat transports; nothing real to give it yet",
    "verification": "already performed on every step by the engine",
    "planning": "this is the planner, not an agent with a tool belt",
}


@dataclass(frozen=True)
class AgentProfile:
    key: str
    name: str
    purpose: str
    tools: tuple[str, ...]
    max_level: int = 2
    route: str = "plan"
    keywords: tuple[str, ...] = ()


def _kw(*words: str) -> tuple[str, ...]:
    return tuple(words)


RESEARCH = AgentProfile(
    "research", "Research Agent",
    "Finds things out: searches the web, opens pages, extracts and compares what they say.",
    ("browser_search", "browser_read", "browser_open", "browser_where", "get_time", "get_date",
     "calculate"),
    max_level=2, route="research",
    keywords=_kw("research", "search", "look up", "lookup", "find out", "web", "internet",
                 "article", "compare", "latest", "news", "price", "who is", "what is"))

CODING = AgentProfile(
    "coding", "Coding Agent",
    "Works on code: reads a project, runs its tests, fixes what fails and reports the diff.",
    ("list_files", "read_file", "search_files", "write_file", "run_tests", "run_command",
     "create_folder", "get_time"),
    max_level=3, route="code",
    keywords=_kw("code", "bug", "error", "test", "tests", "pytest", "refactor", "implement",
                 "fix", "script", "function", "compile", "build", "git", "python"))

COMPUTER = AgentProfile(
    "computer", "Computer Operator",
    "Drives this machine: launches and closes apps, inspects the screen, uses the mouse and keyboard.",
    ("launch_app", "close_app", "list_windows", "run_powershell", "capture_screen",
     "read_screen_text", "type_text", "press_keys", "click_at", "scroll", "system_info",
     "get_time"),
    max_level=3, route="plan",
    keywords=_kw("open app", "launch", "start", "click", "type", "press", "window", "screen",
                 "desktop", "powershell", "close app", "process", "screenshot", "notepad",
                 "calculator", "vs code", "vscode", "chrome"))

FILES = AgentProfile(
    "files", "File Manager",
    "Manages documents: lists, reads, writes, moves, searches and tidies files inside your folders.",
    ("list_files", "read_file", "write_file", "create_folder", "move_path", "delete_path",
     "search_files", "get_time"),
    max_level=3, route="summarize",
    keywords=_kw("file", "files", "folder", "folders", "document", "documents", "pdf", "rename",
                 "move", "delete", "organise", "organize", "downloads", "desktop folder", "notes"))

BROWSER = AgentProfile(
    "browser", "Browser Agent",
    "Acts in the browser like a person: opens sites, searches, follows links, fills forms.",
    ("open_website", "browser_open", "browser_read", "browser_search", "browser_where",
     "browser_click", "browser_click_action", "browser_screenshot", "browser_close", "get_time"),
    max_level=3, route="plan",
    keywords=_kw("youtube", "website", "web page", "webpage", "browse", "tab", "subscribe",
                 "login", "form", "channel", "google", "github"))

MEMORY = AgentProfile(
    "memory", "Memory Agent",
    "Keeps and recalls what matters to you: saves facts, answers from them, forgets on request.",
    ("remember", "recall", "forget", "get_time"),
    max_level=2, route="memory",
    keywords=_kw("remember", "recall", "forget", "memory", "memories", "know about me",
                 "my goal", "my goals", "my skills", "my interests"))

GENERAL = AgentProfile(
    "general", "MIMO",
    "The generalist: any tool the engine has, for goals that do not name a specialty.",
    (), max_level=2, route="plan", keywords=())

ROSTER: tuple[AgentProfile, ...] = (RESEARCH, CODING, COMPUTER, FILES, BROWSER, MEMORY)

_PUNCT = re.compile(r"[^a-z0-9 ]+")


class CappedPolicy:
    """The user's live policy, with a ceiling for one specialist.

    It reads the shared policy on every decision, so changing the global autonomy level in
    Settings takes effect immediately instead of being frozen when an engine was built.
    """

    def __init__(self, policy: AutonomyPolicy, cap: int):
        self.policy, self.cap = policy, cap

    def decide(self, spec):
        decision = self.policy.decide(spec)
        if decision == "allow" and spec.level > self.cap:
            return "confirm"
        return decision

    def to_dict(self) -> dict:
        data = self.policy.to_dict()
        data["agent_max_level"] = self.cap
        return data


class Roster:
    """Picks a specialist for a goal and keeps one engine per specialist."""

    def __init__(self, registry: ToolRegistry, policy: AutonomyPolicy,
                 planner_llm: Callable, answerer: Callable, profiles=ROSTER):
        self.registry = registry
        self.policy = policy
        self._planner_llm = planner_llm
        self._answerer = answerer
        self.profiles = {p.key: p for p in profiles}
        self.profiles[GENERAL.key] = GENERAL
        self._engines: dict[str, AgentEngine] = {}

    # ------------------------------------------------------------------ routing
    def select(self, goal: str) -> AgentProfile:
        text = " " + _PUNCT.sub(" ", (goal or "").lower()) + " "
        best: Optional[AgentProfile] = None
        best_score = 0
        for profile in ROSTER:
            # longer keywords are more specific: "vscode" should beat a bare "code"
            score = sum(len(kw) for kw in profile.keywords if kw in text)
            if score > best_score:
                best, best_score = profile, score
        return best or GENERAL

    # ------------------------------------------------------------------ engines
    def engine_for(self, key: str) -> AgentEngine:
        if key in self._engines:
            return self._engines[key]
        profile = self.profiles.get(key, GENERAL)
        registry = self.registry if profile is GENERAL else self.registry.subset(profile.tools)
        if profile is not GENERAL and not registry.names():
            registry = self.registry                    # a specialty whose tools are missing
        policy = CappedPolicy(self.policy, profile.max_level) if profile.max_level < 3 else self.policy
        engine = AgentEngine(registry, AgentPlanner(registry, self._planner_llm), policy,
                             answerer=self._answerer)
        self._engines[key] = engine
        return engine

    def describe(self) -> list[dict]:
        return [{"key": p.key, "name": p.name, "purpose": p.purpose,
                 "tools": list(p.tools) or ["(all)"], "max_level": p.max_level, "route": p.route}
                for p in (*ROSTER, GENERAL)]

    def resolve(self, key_or_name: str) -> Optional[AgentProfile]:
        raw = (key_or_name or "").strip().lower()
        if raw in self.profiles:
            return self.profiles[raw]
        for p in self.profiles.values():
            if p.name.lower() == raw:
                return p
        return None
