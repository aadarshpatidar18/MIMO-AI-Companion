"""The browser operator, exercised against a real local page (skipped when Playwright is absent)."""
import functools
import http.server
import threading

import pytest

pytest.importorskip("playwright")

from backend.core.agent.registry import ToolError
from backend.tools import browser as b


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("site")
    (root / "index.html").write_text(
        "<html><head><title>Robotics Lab</title></head><body>"
        "<h1>Humanoid robotics research</h1>"
        "<p>Recent work on bipedal locomotion and compliant actuators.</p>"
        "<a href='/second.html'>More research</a>"
        "<button id='sub'>Subscribe</button>"
        "<button id='harmless'>Next page</button>"
        "</body></html>", encoding="utf-8")
    (root / "second.html").write_text(
        "<html><head><title>Second page</title></head><body><h1>Details</h1>"
        "<p>Follow-up notes on control loops.</p></body></html>", encoding="utf-8")

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(scope="module", autouse=True)
def browser_session(site):
    try:
        b.get_session().call(lambda page: page.goto(site))
    except ToolError as e:
        b.reset_session()
        pytest.skip(f"no usable browser here: {e}")
    yield
    b.reset_session()


def test_open_read_and_navigate(site):
    opened = b._open(b._Open(url=site))
    assert opened["title"] == "Robotics Lab" and "bipedal" in opened["preview"]

    read = b._read(b._Read(url=None, max_chars=5000))
    assert "compliant actuators" in read["text"]

    clicked = b._click(b._Click(text="More research", selector=None))
    assert clicked["now"].endswith("/second.html") and clicked["title"] == "Second page"
    assert b._where(b._NoArgs())["url"].endswith("/second.html")


def test_sensitive_control_is_refused_plainly(site):
    b._open(b._Open(url=site))
    with pytest.raises(ToolError, match="consequential"):
        b._click(b._Click(text="Subscribe", selector="#sub"))
    # the page did not move, so nothing happened
    assert b._where(b._NoArgs())["title"] == "Robotics Lab"


def test_harmless_control_can_be_clicked(site):
    b._open(b._Open(url=site))
    assert b._click(b._Click(text="Next page", selector="#harmless"))["title"] == "Robotics Lab"


def test_screenshot_is_written_into_the_allowed_folder(site, tmp_path, monkeypatch):
    monkeypatch.setenv("MIMO_FILE_ROOTS", str(tmp_path))
    dest = tmp_path / "shot.png"
    out = b._screenshot(b._Screenshot(path=str(dest)))
    assert dest.exists() and out["bytes"] > 1000


def test_unreachable_address_reports_kindly():
    with pytest.raises(ToolError):
        b._open(b._Open(url="http://127.0.0.1:9/nothing"))
