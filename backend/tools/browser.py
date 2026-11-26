"""Browser operator: a real Playwright session that can search, read and act on pages.

Playwright's sync API is not thread-safe, so one worker thread owns the browser and every call is
marshalled onto it. If Playwright or a browser binary is missing, the tools say exactly that.

Rules the operator enforces itself (not just in the prompt):
* only http/https URLs, no file:// or javascript:;
* navigating, reading and screenshotting are reversible; clicking is not;
* a click whose target reads like money, messaging, deletion or an account change is refused
  outright - the caller must use `browser_click_action`, which the policy always confirms first.
"""
from __future__ import annotations

import queue
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import quote_plus, urlparse

from pydantic import BaseModel, ConfigDict, Field

from ..core.agent.registry import CONSEQUENTIAL, READ_ONLY, REVERSIBLE, ToolError, ToolRegistry, ToolSpec
from .paths import allowed_roots, resolve_in_roots

SENSITIVE = re.compile(
    r"\b(subscribe|unsubscribe|follow|like|buy|purchase|pay|checkout|order|donate|book|reserve|"
    r"delete|remove|uninstall|send|post|share|confirm|place order|sign up|register|allow|grant|"
    r"install|upgrade|transfer|withdraw|tip)\b", re.IGNORECASE)

SEARCH_ENGINES = {
    "duckduckgo": "https://duckduckgo.com/html/?q={q}",
    "google": "https://www.google.com/search?q={q}",
    "bing": "https://www.bing.com/search?q={q}",
    "youtube": "https://www.youtube.com/results?search_query={q}",
}


def check_url(raw: str) -> str:
    """Only http(s), always with a host."""
    url = (raw or "").strip()
    if not url:
        raise ToolError("A web address is required.")
    if "://" not in url:
        url = "https://" + url.replace(" ", "")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ToolError("I only open http and https addresses.")
    if not parsed.netloc or "." not in parsed.netloc:
        raise ToolError("That does not look like a web address.")
    return url


def is_sensitive(label: str) -> bool:
    return bool(SENSITIVE.search(label or ""))


class _Open(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=3, max_length=2000)


class _Read(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: Optional[str] = Field(default=None, max_length=2000)
    max_chars: int = Field(default=8000, ge=200, le=40_000)


class _Search(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=300)
    engine: str = Field(default="duckduckgo", max_length=20)


class _Click(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: Optional[str] = Field(default=None, max_length=200, description="visible text to click")
    selector: Optional[str] = Field(default=None, max_length=300, description="CSS selector")


class _Screenshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: Optional[str] = Field(default=None, max_length=1000)


class _NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------- the session
class BrowserSession:
    """One browser, one thread, a queue of jobs."""

    def __init__(self, headless: bool = True, timeout_s: float = 30.0):
        self.headless = headless
        self.timeout_s = timeout_s
        self._jobs: "queue.Queue[tuple[Callable[[Any], Any], queue.Queue]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._error: Optional[str] = None
        self._lock = threading.Lock()

    # -- lifecycle -----------------------------------------------------------
    def _start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="mimo-browser", daemon=True)
            self._thread.start()
        self._ready.wait(timeout=45)
        if self._error:
            raise ToolError(self._error)
        if not self._ready.is_set():
            raise ToolError("The browser did not start in time.")

    def _run(self) -> None:
        page = None
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self._error = ("The browser operator needs Playwright: pip install playwright, "
                           "then playwright install chromium.")
            self._ready.set()
            return
        try:
            with sync_playwright() as pw:
                browser = self._launch(pw)
                context = browser.new_context(viewport={"width": 1366, "height": 900},
                                              locale="en-US")
                page = context.new_page()
                page.set_default_timeout(self.timeout_s * 1000)
                self._ready.set()
                while True:
                    fn, reply = self._jobs.get()
                    if fn is None:
                        break
                    try:
                        reply.put(("ok", fn(page)))
                    except Exception as e:                     # noqa: BLE001 - reported to caller
                        reply.put(("err", str(e)))
                context.close()
                browser.close()
        except Exception as e:                                 # noqa: BLE001
            self._error = f"The browser could not start: {e}"
            self._ready.set()

    def _launch(self, pw):
        """Use Playwright's own browser, else a Chrome already installed on this machine."""
        import os
        custom = os.environ.get("MIMO_CHROME_PATH")
        if custom:
            return pw.chromium.launch(headless=self.headless, executable_path=custom)
        try:
            return pw.chromium.launch(headless=self.headless)
        except Exception:
            for channel in ("chrome", "msedge"):
                try:
                    return pw.chromium.launch(headless=self.headless, channel=channel)
                except Exception:
                    continue
            raise

    def call(self, fn: Callable[[Any], Any], timeout: float = 45.0) -> Any:
        self._start()
        reply: "queue.Queue" = queue.Queue(maxsize=1)
        self._jobs.put((fn, reply))
        try:
            kind, payload = reply.get(timeout=timeout)
        except queue.Empty:
            raise ToolError("The page took too long to respond.") from None
        if kind == "err":
            raise ToolError(_friendly(payload))
        return payload

    def close(self) -> None:
        if self._thread and self._thread.is_alive():
            self._jobs.put((None, queue.Queue()))
            self._thread.join(timeout=10)


def _friendly(error: str) -> str:
    low = error.lower()
    if "executable doesn't exist" in low or "browser_type.launch" in low:
        return "No browser binary is installed for Playwright: run 'playwright install chromium'."
    if "timeout" in low:
        return "The page did not finish loading in time."
    if "err_name_not_resolved" in low or "net::" in low:
        return "That address could not be reached. Check the connection or the spelling."
    return f"The browser hit a problem: {error[:300]}"


_session: Optional[BrowserSession] = None
_session_lock = threading.Lock()


def get_session() -> BrowserSession:
    global _session
    with _session_lock:
        if _session is None:
            _session = BrowserSession()
        return _session


def reset_session() -> None:
    """Tests and shutdown: drop the browser so the next call starts a clean one."""
    global _session
    with _session_lock:
        if _session is not None:
            _session.close()
        _session = None


# ---------------------------------------------------------------------------- page helpers
def _text_of(page, limit: int) -> tuple[str, str]:
    title = page.title() or ""
    try:
        body = page.inner_text("body")
    except Exception:                                    # noqa: BLE001
        body = page.content()
    text = "\n".join(line.strip() for line in body.splitlines() if line.strip())
    return title, text[:limit]


def _open(p: _Open) -> dict:
    url = check_url(p.url)
    session = get_session()
    page_info = session.call(lambda page: (page.goto(url, wait_until="domcontentloaded"), page)[1])
    title, text = session.call(lambda page: _text_of(page, 600))
    return {"url": page_info.url, "title": title, "chars": len(text), "preview": text[:600]}


def _read(p: _Read) -> dict:
    session = get_session()

    def job(page):
        if p.url:
            page.goto(check_url(p.url), wait_until="domcontentloaded")
        title, text = _text_of(page, p.max_chars)
        return {"url": page.url, "title": title, "chars": len(text), "text": text}

    return session.call(job)


def _search(p: _Search) -> dict:
    engine = (p.engine or "duckduckgo").lower()
    if engine not in SEARCH_ENGINES:
        raise ToolError(f"search engine must be one of {', '.join(SEARCH_ENGINES)}")
    url = SEARCH_ENGINES[engine].format(q=quote_plus(p.query))
    session = get_session()

    def job(page):
        page.goto(url, wait_until="domcontentloaded")
        results = []
        selectors = {
            "duckduckgo": "a.result__a",
            "google": "a[href^='http'] h3",
            "bing": "li.b_algo h2 a",
            "youtube": "a#video-title",
        }[engine]
        for node in page.query_selector_all(selectors)[:10]:
            title = (node.inner_text() or "").strip()
            href = node.get_attribute("href") or ""
            if engine == "google":
                parent = node.evaluate("n => n.closest('a')?.href || ''")
                href = parent or href
            if title and href.startswith("http"):
                results.append({"title": title[:180], "url": href})
        return {"engine": engine, "query": p.query, "count": len(results), "results": results,
                "page_title": page.title()}

    return session.call(job)


def _locate(page, p: _Click):
    if p.selector:
        node = page.query_selector(p.selector)
    elif p.text:
        node = page.get_by_text(p.text, exact=False).first
    else:
        raise ToolError("Say which element to click: text or selector.")
    if node is None:
        raise ToolError("I could not find that element on the page.")
    return node


def _click(p: _Click) -> dict:
    session = get_session()

    def job(page):
        node = _locate(page, p)
        label = (p.text or p.selector or "").strip()
        try:
            visible = node.inner_text()[:200]
        except Exception:                        # noqa: BLE001
            visible = label
        if is_sensitive(visible or label):
            raise ToolError("That control looks consequential (money, messages, deletion, an "
                            "account change). Use browser_click_action so it asks first.")
        node.click()
        page.wait_for_load_state("domcontentloaded")
        return {"clicked": (p.text or p.selector), "now": page.url, "title": page.title()}

    return session.call(job)


def _click_action(p: _Click) -> dict:
    """Same as a click, but the policy level makes the engine confirm it with the user first."""
    session = get_session()

    def job(page):
        node = _locate(page, p)
        node.click()
        page.wait_for_load_state("domcontentloaded")
        return {"clicked": (p.text or p.selector), "now": page.url, "title": page.title()}

    return session.call(job)


def _screenshot(p: _Screenshot) -> dict:
    roots = allowed_roots()
    if not roots:
        raise ToolError("No folder is allowed to store screenshots.")
    dest = resolve_in_roots(p.path, must_exist=False) if p.path else \
        roots[0] / "mimo-screenshots" / f"page-{datetime.now():%Y%m%d-%H%M%S}.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    session = get_session()
    session.call(lambda page: page.screenshot(path=str(dest), full_page=False))
    return {"path": str(dest), "bytes": dest.stat().st_size,
            "url": session.call(lambda page: page.url)}


def _where(_: _NoArgs) -> dict:
    return get_session().call(lambda page: {"url": page.url, "title": page.title()})


def _close(_: _NoArgs) -> dict:
    reset_session()
    return {"closed": True}


def register_browser_tools(registry: ToolRegistry) -> ToolRegistry:
    registry.register(ToolSpec("browser_open", "Open a web page and show its title and opening text.",
                               _Open, _open, REVERSIBLE,
                               verify=lambda p, out: isinstance(out, dict) and bool(out.get("title"))))
    registry.register(ToolSpec("browser_read", "Read the text of the current page, or of a URL.",
                               _Read, _read, READ_ONLY,
                               verify=lambda p, out: isinstance(out, dict) and out.get("chars", 0) > 0))
    registry.register(ToolSpec("browser_search", "Search the web and list the results.",
                               _Search, _search, READ_ONLY,
                               verify=lambda p, out: isinstance(out, dict) and out.get("count", 0) > 0))
    registry.register(ToolSpec("browser_click", "Follow a link or press a harmless control.",
                               _Click, _click, REVERSIBLE))
    registry.register(ToolSpec("browser_click_action",
                               "Press a control that changes something: subscribe, buy, send, delete. "
                               "Always confirmed with the user first.",
                               _Click, _click_action, CONSEQUENTIAL))
    registry.register(ToolSpec("browser_screenshot", "Screenshot the current page.",
                               _Screenshot, _screenshot, REVERSIBLE))
    registry.register(ToolSpec("browser_where", "Which page is the browser on right now?",
                               _NoArgs, _where, READ_ONLY))
    registry.register(ToolSpec("browser_close", "Close the browser session.", _NoArgs, _close, REVERSIBLE))
    return registry
