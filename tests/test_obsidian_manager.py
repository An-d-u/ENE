import subprocess

from src.ai.obsidian_manager import ObsidianManager


class DummySettings:
    def __init__(self):
        self._values = {
            "obsidian_cli_bin": "obsidian",
            "obsidian_cli_timeout_sec": 7,
            "obsidian_cli_retry_count": 2,
            "obsidian_cli_retry_delay_ms": 1,
        }

    def get(self, key, default=None):
        return self._values.get(key, default)


class DummyObsSettings:
    def get_checked_files(self):
        return ["notes/a.md"]


def test_parse_files_output_extracts_paths():
    output = """
notes/a.md
notes/folder/
├── notes/b.md
|-- notes/c.md
"""
    paths = ObsidianManager._parse_files_output(output)
    assert "notes/a.md" in paths
    assert "notes/b.md" in paths
    assert "notes/c.md" in paths


def test_build_tree_from_paths_creates_dir_and_file_nodes():
    paths = ["notes/a.md", "notes/sub/b.md"]
    nodes = ObsidianManager._build_tree_from_paths(paths)
    assert any(n.get("type") == "dir" and n.get("path") == "notes" for n in nodes)


def test_build_tree_uses_cli_files(monkeypatch):
    manager = ObsidianManager(settings=DummySettings(), obs_settings=DummyObsSettings())

    class DummyCompleted:
        returncode = 0
        stdout = "notes/a.md\nnotes/sub/b.md\n"
        stderr = ""

    monkeypatch.setattr(manager, "_run_cli", lambda args, allow_retry=True: DummyCompleted())

    tree = manager.build_tree()
    assert tree["ok"] is True
    assert tree["checked_files"] == ["notes/a.md"]
    assert tree["nodes"]


def test_read_file_calls_cli(monkeypatch):
    manager = ObsidianManager(settings=DummySettings(), obs_settings=DummyObsSettings())

    class DummyCompleted:
        returncode = 0
        stdout = "hello"
        stderr = ""

    captured = {}

    def fake_run(args, allow_retry=True):
        captured["args"] = args
        captured["allow_retry"] = allow_retry
        return DummyCompleted()

    monkeypatch.setattr(manager, "_run_cli", fake_run)

    text = manager.read_file("notes/a.md")
    assert text == "hello"
    assert captured["args"] == ["read", "notes/a.md"]
    assert captured["allow_retry"] is True


def test_run_cli_windows_uses_powershell_fallback_without_shell_true(monkeypatch):
    manager = ObsidianManager(settings=DummySettings(), obs_settings=DummyObsSettings())

    monkeypatch.setattr("src.ai.obsidian_manager.os.name", "nt")
    monkeypatch.setattr("src.ai.obsidian_manager.shutil.which", lambda _: None)

    calls = {"n": 0, "shell_true": 0, "powershell": 0}

    class DummyCompleted:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls["n"] += 1
        if kwargs.get("shell") is True:
            calls["shell_true"] += 1
        if kwargs.get("shell") is False:
            if isinstance(cmd, list) and len(cmd) >= 3 and cmd[0] == "powershell" and cmd[1] == "-Command":
                calls["powershell"] += 1
                return DummyCompleted()
            raise FileNotFoundError("not found")
        raise AssertionError("shell=True는 호출되면 안 됩니다.")

    monkeypatch.setattr(subprocess, "run", fake_run)

    completed = manager._run_cli(["files"])
    assert completed.stdout == "ok"
    assert calls["n"] >= 2
    assert calls["shell_true"] == 0
    assert calls["powershell"] == 1


def test_run_cli_windows_powershell_fallback_when_not_recognized(monkeypatch):
    manager = ObsidianManager(settings=DummySettings(), obs_settings=DummyObsSettings())

    monkeypatch.setattr("src.ai.obsidian_manager.os.name", "nt")
    monkeypatch.setattr("src.ai.obsidian_manager.shutil.which", lambda _: None)

    class NotFoundCompleted:
        returncode = 1
        stdout = ""
        stderr = "'obsidian' is not recognized as an internal or external command,"

    class OkCompleted:
        returncode = 0
        stdout = "ok"
        stderr = ""

    captured = {"ps_called": False}

    def fake_run(cmd, **kwargs):
        if kwargs.get("shell") is False:
            if isinstance(cmd, list) and len(cmd) >= 3 and cmd[0] == "powershell" and cmd[1] == "-Command":
                captured["ps_called"] = True
                return OkCompleted()
            raise FileNotFoundError("not found")
        return NotFoundCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)

    completed = manager._run_cli(["files"])
    assert completed.stdout == "ok"
    assert captured["ps_called"] is True


def test_read_file_failure_marks_manager_disconnected(monkeypatch):
    manager = ObsidianManager(settings=DummySettings(), obs_settings=DummyObsSettings())
    manager._tree_connection_ok = True

    class DummyCompleted:
        returncode = 1
        stdout = ""
        stderr = "mock fail"

    monkeypatch.setattr(manager, "_run_cli", lambda args, allow_retry=True: DummyCompleted())

    try:
        manager.read_file("notes/a.md", allow_retry=False)
    except RuntimeError:
        pass

    assert manager.is_connected() is False


def test_run_cli_supports_multi_token_cli_bin(monkeypatch):
    manager = ObsidianManager(settings=DummySettings(), obs_settings=DummyObsSettings())
    manager.settings._values["obsidian_cli_bin"] = "npx obsidian"

    captured = {}

    class DummyCompleted:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["shell"] = kwargs.get("shell")
        return DummyCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)

    completed = manager._run_cli(["files"])
    assert completed.stdout == "ok"
    assert captured["shell"] is False
    assert captured["cmd"] == ["npx", "obsidian", "files"]


def test_run_cli_retries_non_mutating_command(monkeypatch):
    manager = ObsidianManager(settings=DummySettings(), obs_settings=DummyObsSettings())
    call_count = {"n": 0}

    class FailedCompleted:
        returncode = 1
        stdout = ""
        stderr = ""

    class OkCompleted:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_once(_args):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return FailedCompleted()
        return OkCompleted()

    monkeypatch.setattr(manager, "_run_cli_once", fake_once)

    completed = manager._run_cli(["files"])
    assert completed.returncode == 0
    assert call_count["n"] == 2


def test_run_cli_does_not_retry_mutating_command(monkeypatch):
    manager = ObsidianManager(settings=DummySettings(), obs_settings=DummyObsSettings())
    call_count = {"n": 0}

    class FailedCompleted:
        returncode = 1
        stdout = ""
        stderr = ""

    def fake_once(_args):
        call_count["n"] += 1
        return FailedCompleted()

    monkeypatch.setattr(manager, "_run_cli_once", fake_once)
    completed = manager._run_cli(["append", "notes/a.md", "hello"])
    assert completed.returncode == 1
    assert call_count["n"] == 1


def test_resolve_cli_candidates_excludes_desktop_app_fallback(monkeypatch):
    manager = ObsidianManager(settings=DummySettings(), obs_settings=DummyObsSettings())
    monkeypatch.setattr("src.ai.obsidian_manager.os.name", "nt")
    monkeypatch.setattr("src.ai.obsidian_manager.shutil.which", lambda _: None)

    candidates = manager._resolve_cli_candidates()
    joined = "\n".join(candidates).lower()
    assert "program files\\obsidian\\obsidian.exe" not in joined
    assert "programs\\obsidian\\obsidian.exe" not in joined


def test_get_checked_file_contents_uses_settings_limits(monkeypatch):
    manager = ObsidianManager(settings=DummySettings(), obs_settings=DummyObsSettings())
    manager.settings._values["obsidian_checked_max_chars_per_file"] = 555
    manager.settings._values["obsidian_checked_total_max_chars"] = 777

    monkeypatch.setattr(manager, "read_file", lambda rel, allow_retry=True: "a" * 1000)

    checked_contents = manager.get_checked_file_contents()

    assert checked_contents == [("notes/a.md", "a" * 555)]
