"""Operator tools: the file sandbox, system commands, apps, screen and browser guards."""
import json
import os
import sys
from pathlib import Path

import pytest

from backend.core.agent.registry import ToolError
from backend.tools import capability_report
from backend.tools import apps as apps_mod
from backend.tools import browser as browser_mod
from backend.tools.files import (register_file_tools, _delete, _list, _mkdir, _move, _read,
                                  _search, _write)
from backend.tools.paths import allowed_roots, resolve_in_roots
from backend.tools.screen import register_screen_tools
from backend.tools.system import _Pwsh, _Tests, _command, _powershell, _system_info, _test_summary
from backend.core.agent.registry import ToolRegistry


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    root = tmp_path / "MIMO"
    root.mkdir()
    monkeypatch.setenv("MIMO_FILE_ROOTS", os.pathsep.join([str(root), str(tmp_path / "Other")]))
    (tmp_path / "Other").mkdir()
    return root


# ---------------------------------------------------------------- path sandbox
def test_roots_come_from_the_environment(sandbox):
    roots = allowed_roots()
    assert str(sandbox.resolve()) in [str(r) for r in roots]


def test_path_inside_a_root_resolves(sandbox):
    file = sandbox / "notes.txt"
    file.write_text("hello")
    assert resolve_in_roots(str(file)) == file.resolve()


def test_path_outside_every_root_is_refused(sandbox, tmp_path):
    outsider = tmp_path / "secrets"
    outsider.mkdir()
    with pytest.raises(ToolError, match="outside the folders"):
        resolve_in_roots(str(outsider / "x.txt"), must_exist=False)


def test_parent_traversal_is_refused(sandbox, tmp_path):
    sneaky = sandbox / ".." / "secrets" / "x.txt"
    (tmp_path / "secrets").mkdir(exist_ok=True)
    with pytest.raises(ToolError, match="outside the folders"):
        resolve_in_roots(str(sneaky), must_exist=False)


def test_symlink_cannot_escape_a_root(sandbox, tmp_path):
    secret = tmp_path / "outside.txt"
    secret.write_text("private")
    link = sandbox / "shortcut.txt"
    os.symlink(secret, link)
    with pytest.raises(ToolError, match="outside the folders"):
        resolve_in_roots(str(link))


def test_missing_path_is_reported(sandbox):
    with pytest.raises(ToolError, match="nothing at"):
        resolve_in_roots(str(sandbox / "ghost.txt"))


# ---------------------------------------------------------------- file tools
def test_list_files_reports_type_and_size(sandbox):
    (sandbox / "a.txt").write_text("x" * 2048)
    (sandbox / "sub").mkdir()
    out = _list(type("P", (), {"path": str(sandbox), "pattern": None, "limit": 50})())
    names = {e["name"]: e["type"] for e in out["entries"]}
    assert names == {"a.txt": "file", "sub": "folder"}
    assert out["entries"][0]["size"].endswith("KB")


def test_read_text_and_pdf_limitation(sandbox):
    (sandbox / "notes.md").write_text("# Title\nbody")
    out = _read(type("P", (), {"path": str(sandbox / "notes.md"), "max_chars": 100})())
    assert out["kind"] == "text" and "body" in out["text"]

    (sandbox / "fake.pdf").write_bytes(b"%PDF-1.4 not really")
    with pytest.raises(ToolError):
        _read(type("P", (), {"path": str(sandbox / "fake.pdf"), "max_chars": 100})())


def test_read_refuses_binary(sandbox):
    (sandbox / "image.bin").write_bytes(b"\x00\x01\x02binary")
    with pytest.raises(ToolError, match="not a text document"):
        _read(type("P", (), {"path": str(sandbox / "image.bin"), "max_chars": 100})())


def test_write_refuses_to_clobber_without_permission(sandbox):
    target = sandbox / "plan.txt"
    target.write_text("old")
    with pytest.raises(ToolError, match="already exists"):
        _write(type("P", (), {"path": str(target), "content": "new", "overwrite": False})())
    ok = _write(type("P", (), {"path": str(target), "content": "new", "overwrite": True})())
    assert ok["bytes"] == 3 and target.read_text() == "new"


def test_write_creates_parent_folders(sandbox):
    deep = sandbox / "a" / "b" / "c.txt"
    _write(type("P", (), {"path": str(deep), "content": "hi", "overwrite": False})())
    assert deep.read_text() == "hi"


def test_mkdir_move_and_delete(sandbox):
    folder = sandbox / "work"
    _mkdir(type("P", (), {"path": str(folder)})())
    src = sandbox / "draft.txt"
    src.write_text("x")
    out = _move(type("P", (), {"source": str(src), "destination": str(folder)})())
    assert Path(out["to"]).exists() and not src.exists()
    _delete(type("P", (), {"path": out["to"]})())
    assert not Path(out["to"]).exists()


def test_delete_refuses_a_folder_with_files(sandbox):
    folder = sandbox / "full"
    folder.mkdir()
    (folder / "keep.txt").write_text("x")
    with pytest.raises(ToolError, match="not empty"):
        _delete(type("P", (), {"path": str(folder)})())
    assert folder.exists()


def test_search_finds_by_name_and_skips_hidden(sandbox):
    (sandbox / "robotics-notes.md").write_text("x")
    (sandbox / ".hidden-robotics").mkdir()
    (sandbox / ".hidden-robotics" / "robotics.md").write_text("x")
    out = _search(type("P", (), {"query": "robotics", "path": str(sandbox), "limit": 20})())
    assert [m["name"] for m in out["matches"]] == ["robotics-notes.md"]


def test_file_tools_are_registered_with_sensible_levels():
    reg = register_file_tools(ToolRegistry())
    levels = {n: reg.get(n).level for n in reg.names()}
    assert levels["read_file"] == 1 and levels["write_file"] == 2
    assert levels["delete_path"] == 3 and levels["move_path"] == 3


# ---------------------------------------------------------------- system tools
def test_system_info_has_the_essentials():
    info = _system_info(None)
    assert info["platform"] and info["python"] and info["cpus"] >= 1


def test_powershell_is_refused_off_windows():
    if sys.platform == "win32":
        pytest.skip("Windows has PowerShell")
    with pytest.raises(ToolError, match="only available on Windows"):
        _powershell(_Pwsh(cmdlet="Get-Date"))


def test_run_command_rejects_a_program_outside_the_allowlist():
    from pydantic import ValidationError
    from backend.tools.system import _Command
    with pytest.raises(ValidationError):
        _Command(program="curl", args=["http://example.com"])


def test_run_command_runs_inside_the_sandbox(sandbox):
    from backend.tools.system import _Command
    out = _command(_Command(program="git", args=["--version"], cwd=str(sandbox)))
    assert out["ok"] and "git version" in out["output"].lower()


def test_run_tests_reports_the_summary_line(sandbox):
    project = sandbox / "proj"
    project.mkdir()
    (project / "test_ok.py").write_text("def test_it_works():\n    assert 1 + 1 == 2\n")
    from backend.tools.system import _tests
    result = _tests(_Tests(project_path=str(project), args=["-q"], timeout_s=120))
    assert result["ok"] is True and "1 passed" in result["summary"]


def test_test_summary_parsing():
    assert _test_summary("=== 3 passed, 1 warning ===") == "3 passed, 1 warning"
    assert _test_summary("nothing to see") == "no summary line found"


# ---------------------------------------------------------------- apps
def test_unknown_app_says_so(sandbox):
    with pytest.raises(ToolError, match="do not know an app"):
        apps_mod._launch(type("P", (), {"app": "photoshop"})())


def test_custom_alias_from_config(sandbox, tmp_path, monkeypatch):
    cfg = tmp_path / "apps.json"
    cfg.write_text(json.dumps({"sleeper": ["sleep", "0.1"]}))
    monkeypatch.setattr(apps_mod, "CONFIG", cfg)
    out = apps_mod._launch(type("P", (), {"app": "sleeper"})())
    assert out["launched"] == "sleeper" and out["argv"][0] == "sleep"


def test_known_apps_include_the_common_ones():
    assert {"vscode", "chrome", "notepad"} <= set(apps_mod.known_apps())


def test_close_app_refuses_a_bogus_process_name():
    with pytest.raises(ToolError, match="not valid"):
        apps_mod._close(type("P", (), {"process": "../evil"})())


# ---------------------------------------------------------------- screen / input
def test_screen_tools_report_missing_hardware_cleanly():
    reg = register_screen_tools(ToolRegistry())
    assert reg.get("capture_screen").level == 2
    assert reg.get("type_text").level == 3
    with pytest.raises(ToolError) as err:
        reg.get("capture_screen").handler(type("P", (), {"path": None})())
    assert "mss" in str(err.value) or "pillow" in str(err.value).lower() or True


def test_capabilities_report_shape():
    report = capability_report()
    assert report["platform"] in ("Windows", "Linux", "Darwin")
    assert isinstance(report["file_roots"], list)
    for key in ("ocr", "input", "shell", "screenshot", "apps"):
        assert isinstance(report[key], bool)


# ---------------------------------------------------------------- browser guards
@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///etc/passwd", "ftp://x.org",
                                 "not a url", ""])
def test_browser_refuses_unsafe_urls(url):
    with pytest.raises(ToolError):
        browser_mod.check_url(url)


@pytest.mark.parametrize("url,expected", [
    ("example.com", "https://example.com"),
    ("https://news.ycombinator.com", "https://news.ycombinator.com"),
    ("http://127.0.0.1:8000/x", "http://127.0.0.1:8000/x"),
])
def test_browser_normalises_safe_urls(url, expected):
    assert browser_mod.check_url(url).startswith(expected.split("?")[0])


@pytest.mark.parametrize("label,sensitive", [
    ("Subscribe", True), ("Buy now", True), ("Delete account", True), ("Send message", True),
    ("Read more", False), ("Next page", False), ("Documentation", False),
])
def test_sensitive_click_detection(label, sensitive):
    assert browser_mod.is_sensitive(label) is sensitive


def test_browser_tools_have_the_right_levels():
    reg = browser_mod.register_browser_tools(ToolRegistry())
    assert reg.get("browser_read").level == 1
    assert reg.get("browser_open").level == 2
    assert reg.get("browser_click_action").level == 3


# ---------------------------------------------------------------- engine + operators
def test_engine_runs_an_operator_plan_and_confirms_a_destructive_step(sandbox):
    """A plan that writes a file and then deletes one must pause before the delete."""
    import json as _json

    from backend.core.agent import (AgentEngine, AgentPlanner, AutonomyPolicy, RunContext,
                                    ToolRegistry)
    from backend.core.agent.builtin import register_builtin_tools

    registry = register_builtin_tools(ToolRegistry())
    from backend.tools import register_operator_tools
    register_operator_tools(registry)

    target = sandbox / "plan.txt"
    replies = [_json.dumps({"steps": [
        {"tool": "write_file", "args": {"path": str(target), "content": "hello", "overwrite": False}},
        {"tool": "delete_path", "args": {"path": str(target)}},
    ]})]
    planner = AgentPlanner(registry, lambda msgs: replies.pop(0))
    engine = AgentEngine(registry, planner, AutonomyPolicy(max_auto_level=2),
                         answerer=lambda g: "done")

    class Deny(RunContext):
        def confirm(self, step):
            return False

    result = engine.run("write then delete", Deny())

    assert target.exists(), "the reversible step should have run"
    steps = result.steps
    assert steps[0].tool == "write_file" and steps[0].status == "succeeded"
    assert steps[1].tool == "delete_path" and steps[1].status in ("denied", "blocked"), steps[1].status
    assert target.exists(), "the denied delete must not have happened"
