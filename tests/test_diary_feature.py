import asyncio
import builtins
from pathlib import Path
import sys

from PyQt6.QtCore import QCoreApplication

from src.ai.diary_service import DiaryService
from src.ai.prompt import get_system_prompt
from src.core.bridge import WebBridge


def _ensure_qt_app():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


def test_prompt_includes_sub_prompt_by_default():
    prompt_with_sub = get_system_prompt()
    prompt_without_sub = get_system_prompt(include_sub_prompt=False)

    assert "[감정 표현 규칙]" in prompt_with_sub
    assert "[일본어 응답 규칙]" in prompt_with_sub
    assert "[감정 표현 규칙]" not in prompt_without_sub
    assert "[일본어 응답 규칙]" not in prompt_without_sub


def test_prompt_falls_back_when_sub_prompt_is_missing(monkeypatch):
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.endswith("sub_prompt"):
            raise ModuleNotFoundError("sub_prompt not found")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.delitem(sys.modules, "src.ai.sub_prompt", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    prompt = get_system_prompt(include_sub_prompt=True)
    assert "[감정 표현 규칙]" not in prompt
    assert "[일본어 응답 규칙]" not in prompt


def test_diary_command_parse():
    is_diary, body = DiaryService.parse_diary_command("/diary 오늘 있었던 일을 일기로 써줘")
    assert is_diary is True
    assert body == "오늘 있었던 일을 일기로 써줘"

    is_diary2, body2 = DiaryService.parse_diary_command("/diary   ")
    assert is_diary2 is True
    assert body2 == ""

    is_diary3, body3 = DiaryService.parse_diary_command("일반 메시지")
    assert is_diary3 is False
    assert body3 == ""


def test_obs_command_parse():
    is_obs, body = DiaryService.parse_obs_command("/obs ENE/Projects/AI.md에 회의 요약 추가")
    assert is_obs is True
    assert body == "ENE/Projects/AI.md에 회의 요약 추가"

    is_obs2, body2 = DiaryService.parse_obs_command("/obs   ")
    assert is_obs2 is True
    assert body2 == ""

    is_obs3, body3 = DiaryService.parse_obs_command("일반 메시지")
    assert is_obs3 is False
    assert body3 == ""


def test_note_command_parse():
    is_note, body = DiaryService.parse_note_command("/note test.md 요약해줘")
    assert is_note is True
    assert body == "test.md 요약해줘"

    is_note2, body2 = DiaryService.parse_note_command("/note   ")
    assert is_note2 is True
    assert body2 == ""

    is_note3, body3 = DiaryService.parse_note_command("일반 메시지")
    assert is_note3 is False
    assert body3 == ""


def test_diary_save_markdown_creates_utf8_bom_file(tmp_path: Path):
    service = DiaryService(tmp_path / "diary")
    result = service.save_markdown("기획서 초안을 써줘", "# 제목\n\n본문")

    saved_path = Path(result.absolute_path)
    assert saved_path.exists()
    assert saved_path.parent.name == "diary"
    assert saved_path.suffix == ".md"

    data = saved_path.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf")


def test_diary_save_local_only_when_cli_disabled(tmp_path: Path):
    class DummySettings:
        def get(self, key: str, default=None):
            values = {
                "obsidian_cli_enabled": False,
                "obsidian_cli_command": "obsidian-cli --file \"{file_path}\"",
            }
            return values.get(key, default)

    service = DiaryService(tmp_path / "diary", settings=DummySettings())
    result = service.save_markdown_via_priority("연결 테스트", "# 문서")
    assert result.storage_target == "local_only"
    assert result.obsidian_cli_invoked is False
    assert result.obsidian_cli_error == ""


def test_diary_save_cli_primary_success(tmp_path: Path, monkeypatch):
    class DummySettings:
        def get(self, key: str, default=None):
            values = {
                "obsidian_cli_enabled": True,
                "obsidian_cli_primary_for_diary": True,
                "diary_keep_local_copy_on_cli_success": False,
                "obsidian_cli_command": "obsidian-cli --file \"{file_path}\" --name \"{file_name}\"",
                "obsidian_cli_timeout_sec": 5,
            }
            return values.get(key, default)

    captured = {}

    class DummyCompleted:
        returncode = 0
        stderr = ""

    def fake_run(command, shell, text, capture_output, timeout):
        captured["command"] = command
        captured["timeout"] = timeout
        return DummyCompleted()

    monkeypatch.setattr("src.ai.diary_service.subprocess.run", fake_run)

    service = DiaryService(tmp_path / "diary", settings=DummySettings())
    result = service.save_markdown_via_priority("연결 테스트", "# 문서")

    assert result.storage_target == "obsidian"
    assert result.obsidian_cli_invoked is True
    assert result.obsidian_cli_error == ""
    assert result.obsidian_output_path
    assert "obsidian-cli" in captured["command"]
    assert captured["timeout"] == 5
    assert list((tmp_path / "diary").glob("*.md")) == []


def test_diary_save_cli_primary_failure_fallback_local(tmp_path: Path, monkeypatch):
    class DummySettings:
        def get(self, key: str, default=None):
            values = {
                "obsidian_cli_enabled": True,
                "obsidian_cli_primary_for_diary": True,
                "diary_keep_local_copy_on_cli_success": False,
                "obsidian_cli_command": "obsidian-cli --file \"{file_path}\"",
                "obsidian_cli_timeout_sec": 5,
            }
            return values.get(key, default)

    class DummyCompleted:
        returncode = 1
        stderr = "mock fail"

    def fake_run(command, shell, text, capture_output, timeout):
        return DummyCompleted()

    monkeypatch.setattr("src.ai.diary_service.subprocess.run", fake_run)

    service = DiaryService(tmp_path / "diary", settings=DummySettings())
    result = service.save_markdown_via_priority("연결 테스트", "# 문서")

    assert result.storage_target == "local_fallback"
    assert result.obsidian_cli_invoked is True
    assert "mock fail" in result.obsidian_cli_error
    saved_files = list((tmp_path / "diary").glob("*.md"))
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes().startswith(b"\xef\xbb\xbf")


def test_bridge_handles_diary_without_conversation_buffer(monkeypatch):
    _ensure_qt_app()

    class DummyLLM:
        async def generate_markdown_document(self, message: str) -> str:
            return "# 테스트\n"

        async def generate_diary_completion_reply(self, context_message: str):
            return "성공적으로 파일 작성에 완료되었습니다.", "normal", "", []

    bridge = WebBridge()
    bridge.llm_client = DummyLLM()

    captured = {}

    def fake_start(body: str, message_with_time: str, use_obsidian_priority: bool = False):
        captured["body"] = body
        captured["message"] = message_with_time
        captured["use_obsidian_priority"] = use_obsidian_priority

    monkeypatch.setattr(bridge, "_start_diary_worker", fake_start)

    handled = bridge._handle_diary_command("/diary 오늘 있었던 일을 일기로 써줘")
    assert handled is True
    assert captured["body"] == "오늘 있었던 일을 일기로 써줘"
    assert "[현재 시각:" in captured["message"]
    assert captured["use_obsidian_priority"] is False
    assert bridge.conversation_buffer == []


def test_bridge_diary_empty_body_emits_error_message():
    _ensure_qt_app()

    class DummyLLM:
        pass

    bridge = WebBridge()
    bridge.llm_client = DummyLLM()

    received = []
    bridge.message_received.connect(lambda text, emotion: received.append((text, emotion)))

    handled = bridge._handle_diary_command("/diary")
    assert handled is True
    assert received
    assert "`/diary` 뒤에 작성할 내용을 함께 입력해 주세요." in received[-1][0]


def test_bridge_send_to_ai_routes_diary(monkeypatch):
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.llm_client = object()

    called = {"diary": 0, "normal": 0}

    def fake_obs(message: str) -> bool:
        return False

    def fake_handle(message: str) -> bool:
        called["diary"] += 1
        return True

    def fake_start(*args, **kwargs):
        called["normal"] += 1

    monkeypatch.setattr(bridge, "_handle_obs_command", fake_obs)
    monkeypatch.setattr(bridge, "_handle_diary_command", fake_handle)
    monkeypatch.setattr(bridge, "_start_ai_worker", fake_start)

    bridge.send_to_ai("/diary 테스트")

    assert called["diary"] == 1
    assert called["normal"] == 0


def test_bridge_send_to_ai_routes_obs(monkeypatch):
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.llm_client = object()

    called = {"obs": 0, "diary": 0}

    def fake_obs(message: str) -> bool:
        called["obs"] += 1
        return True

    def fake_diary(message: str) -> bool:
        called["diary"] += 1
        return False

    monkeypatch.setattr(bridge, "_handle_obs_command", fake_obs)
    monkeypatch.setattr(bridge, "_handle_diary_command", fake_diary)

    bridge.send_to_ai("/obs 테스트")

    assert called["obs"] == 1
    assert called["diary"] == 0


def test_bridge_send_to_ai_routes_note(monkeypatch):
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.llm_client = object()

    called = {"note": 0, "obs": 0, "diary": 0}

    def fake_note(message: str) -> bool:
        called["note"] += 1
        return True

    def fake_obs(message: str) -> bool:
        called["obs"] += 1
        return False

    def fake_diary(message: str) -> bool:
        called["diary"] += 1
        return False

    monkeypatch.setattr(bridge, "_handle_note_command", fake_note)
    monkeypatch.setattr(bridge, "_handle_obs_command", fake_obs)
    monkeypatch.setattr(bridge, "_handle_diary_command", fake_diary)

    bridge.send_to_ai("/note 테스트")

    assert called["note"] == 1
    assert called["obs"] == 0
    assert called["diary"] == 0


def test_edit_last_user_message_reroutes_to_note_command(monkeypatch):
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.llm_client = object()
    bridge.conversation_buffer = [
        ("user", "원래 질문", "2026-03-18 10:00"),
        ("assistant", "원래 답변", "2026-03-18 10:00"),
    ]
    bridge._last_request_payload = {
        "type": "text",
        "message": "원래 질문",
        "message_with_time": "[현재 시각: 2026-03-18 10:00]\n원래 질문",
        "images": [],
    }

    called = {"rollback": 0, "note": 0, "normal": 0}

    monkeypatch.setattr(bridge, "_rollback_last_turn_pair_for_retry", lambda: called.__setitem__("rollback", called["rollback"] + 1) or True)

    def fake_note(message: str) -> bool:
        called["note"] += 1
        assert message == "/note 테스트 문서를 만들어줘"
        return True

    def fake_start(*args, **kwargs):
        called["normal"] += 1

    monkeypatch.setattr(bridge, "_handle_note_command", fake_note)
    monkeypatch.setattr(bridge, "_handle_obs_command", lambda message: False)
    monkeypatch.setattr(bridge, "_handle_diary_command", lambda message: False)
    monkeypatch.setattr(bridge, "_start_ai_worker", fake_start)

    bridge.edit_last_user_message("/note 테스트 문서를 만들어줘")

    assert called["rollback"] == 1
    assert called["note"] == 1
    assert called["normal"] == 0
    assert bridge.conversation_buffer == []


def test_bridge_note_recent_context_includes_last_n_turns(monkeypatch):
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.llm_client = object()
    bridge.conversation_buffer = [
        ("user", "첫 질문", "2026-03-07 00:01"),
        ("assistant", "첫 답변", "2026-03-07 00:01"),
        ("user", "둘째 질문", "2026-03-07 00:02"),
        ("assistant", "둘째 답변", "2026-03-07 00:02"),
    ]

    class DummySettings:
        def get(self, key, default=None):
            values = {
                "note_include_recent_context": True,
                "note_recent_context_turns": 1,
            }
            return values.get(key, default)

    bridge.settings = DummySettings()
    captured = {}

    def fake_start(note_request: str, message_with_time: str, note_recent_context: str = ""):
        captured["note_request"] = note_request
        captured["message_with_time"] = message_with_time
        captured["note_recent_context"] = note_recent_context

    monkeypatch.setattr(bridge, "_start_note_worker", fake_start)

    handled = bridge._handle_note_command("/note 자기소개서 수정해줘")
    assert handled is True
    assert captured["note_request"] == "자기소개서 수정해줘"
    assert "둘째 질문" in captured["note_recent_context"]
    assert "둘째 답변" in captured["note_recent_context"]
    assert "첫 질문" not in captured["note_recent_context"]


def test_bridge_note_recent_context_zero_includes_full_session(monkeypatch):
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.llm_client = object()
    bridge.conversation_buffer = [
        ("user", "첫 질문", "2026-03-07 00:01"),
        ("assistant", "첫 답변", "2026-03-07 00:01"),
        ("user", "둘째 질문", "2026-03-07 00:02"),
        ("assistant", "둘째 답변", "2026-03-07 00:02"),
    ]

    class DummySettings:
        def get(self, key, default=None):
            values = {
                "note_include_recent_context": True,
                "note_recent_context_turns": 0,
            }
            return values.get(key, default)

    bridge.settings = DummySettings()
    captured = {}

    def fake_start(note_request: str, message_with_time: str, note_recent_context: str = ""):
        captured["note_recent_context"] = note_recent_context

    monkeypatch.setattr(bridge, "_start_note_worker", fake_start)

    handled = bridge._handle_note_command("/note 자기소개서 수정해줘")
    assert handled is True
    assert "첫 질문" in captured["note_recent_context"]
    assert "첫 답변" in captured["note_recent_context"]
    assert "둘째 질문" in captured["note_recent_context"]
    assert "둘째 답변" in captured["note_recent_context"]


def test_bridge_general_chat_includes_checked_obsidian_context(monkeypatch):
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.llm_client = object()
    bridge._obsidian_integration_activated = True
    bridge._cached_checked_files_signature = ("notes/test.md",)
    bridge._cached_checked_files_context = "[Obsidian 체크된 파일 본문]\n[파일:notes/test.md]\n# 테스트\n본문"
    monkeypatch.setattr(bridge.obs_settings, "get_checked_files", lambda: ["notes/test.md"])

    captured = {}

    def fake_note(message: str) -> bool:
        return False

    def fake_obs(message: str) -> bool:
        return False

    def fake_diary(message: str) -> bool:
        return False

    def fake_start(message_with_time: str, images_data=None, memory_search_text: str = ""):
        captured["message_with_time"] = message_with_time

    monkeypatch.setattr(bridge, "_handle_note_command", fake_note)
    monkeypatch.setattr(bridge, "_handle_obs_command", fake_obs)
    monkeypatch.setattr(bridge, "_handle_diary_command", fake_diary)
    monkeypatch.setattr(bridge, "_start_ai_worker", fake_start)

    bridge.send_to_ai("안녕")

    assert "[Obsidian 체크된 파일 본문]" in captured["message_with_time"]
    assert "[파일:notes/test.md]" in captured["message_with_time"]
    assert "# 테스트" in captured["message_with_time"]
    assert "[사용자 메시지]\n안녕" in captured["message_with_time"]


def test_bridge_general_chat_skips_obsidian_context_when_disconnected(monkeypatch):
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.llm_client = object()
    monkeypatch.setattr(bridge.obs_settings, "get_checked_files", lambda: [])
    captured = {}

    def fake_note(message: str) -> bool:
        return False

    def fake_obs(message: str) -> bool:
        return False

    def fake_diary(message: str) -> bool:
        return False

    def fake_start(message_with_time: str, images_data=None, memory_search_text: str = ""):
        captured["message_with_time"] = message_with_time

    monkeypatch.setattr(bridge, "_handle_note_command", fake_note)
    monkeypatch.setattr(bridge, "_handle_obs_command", fake_obs)
    monkeypatch.setattr(bridge, "_handle_diary_command", fake_diary)
    monkeypatch.setattr(bridge, "_start_ai_worker", fake_start)

    bridge.send_to_ai("안녕")

    assert "[Obsidian 체크된 파일 본문]" not in captured["message_with_time"]
    assert captured["message_with_time"].endswith("\n안녕")


def test_bridge_general_chat_cache_miss_before_obsidian_activation_skips_background_refresh(monkeypatch):
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.llm_client = object()
    monkeypatch.setattr(bridge.obs_settings, "get_checked_files", lambda: ["notes/test.md"])

    captured = {"refresh_called": 0}

    def fake_refresh(force: bool = False):
        captured["refresh_called"] += 1

    def fake_start(message_with_time: str, images_data=None, memory_search_text: str = ""):
        captured["message_with_time"] = message_with_time

    monkeypatch.setattr(bridge, "_schedule_checked_files_context_refresh", fake_refresh)
    monkeypatch.setattr(bridge, "_handle_note_command", lambda message: False)
    monkeypatch.setattr(bridge, "_handle_obs_command", lambda message: False)
    monkeypatch.setattr(bridge, "_handle_diary_command", lambda message: False)
    monkeypatch.setattr(bridge, "_start_ai_worker", fake_start)

    bridge.send_to_ai("안녕")

    assert captured["refresh_called"] == 0
    assert "[Obsidian 체크된 파일 본문]" not in captured["message_with_time"]


def test_bridge_general_chat_cache_miss_after_obsidian_activation_schedules_background_refresh(monkeypatch):
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.llm_client = object()
    bridge._obsidian_integration_activated = True
    monkeypatch.setattr(bridge.obs_settings, "get_checked_files", lambda: ["notes/test.md"])

    captured = {"refresh_called": 0}

    def fake_refresh(force: bool = False):
        captured["refresh_called"] += 1

    def fake_start(message_with_time: str, images_data=None, memory_search_text: str = ""):
        captured["message_with_time"] = message_with_time

    monkeypatch.setattr(bridge, "_schedule_checked_files_context_refresh", fake_refresh)
    monkeypatch.setattr(bridge, "_handle_note_command", lambda message: False)
    monkeypatch.setattr(bridge, "_handle_obs_command", lambda message: False)
    monkeypatch.setattr(bridge, "_handle_diary_command", lambda message: False)
    monkeypatch.setattr(bridge, "_start_ai_worker", fake_start)

    bridge.send_to_ai("안녕")

    assert captured["refresh_called"] == 1
    assert "[Obsidian 체크된 파일 본문]" not in captured["message_with_time"]


def test_bridge_toggle_obs_panel_activates_obsidian_lazy_connection(monkeypatch):
    _ensure_qt_app()

    bridge = WebBridge()

    class DummyPanel:
        def __init__(self):
            self._visible = False

        def isVisible(self):
            return self._visible

        def show(self):
            self._visible = True

        def hide(self):
            self._visible = False

        def raise_(self):
            return None

        def activateWindow(self):
            return None

        def _ensure_visible_on_screen(self):
            return None

    bridge.obs_panel_window = DummyPanel()

    captured = {"activated": 0, "scheduled": 0}

    monkeypatch.setattr(
        bridge,
        "_activate_obsidian_integration",
        lambda: captured.__setitem__("activated", captured["activated"] + 1),
        raising=False,
    )
    monkeypatch.setattr("src.core.bridge.QTimer.singleShot", lambda ms, callback: captured.__setitem__("scheduled", captured["scheduled"] + 1))

    bridge.toggle_obs_panel()

    assert captured["activated"] == 1
    assert captured["scheduled"] == 1


def test_bridge_obs_tree_failed_payload_schedules_retry(monkeypatch):
    _ensure_qt_app()

    bridge = WebBridge()

    class DummyPanel:
        def isVisible(self):
            return True

    bridge.obs_panel_window = DummyPanel()
    bridge._obs_tree_retry_remaining = 2
    captured = {}

    monkeypatch.setattr(bridge.obs_tree_retry_timer, "start", lambda ms: captured.setdefault("ms", ms))

    bridge._on_obs_tree_ready('{"ok": false, "error": "mock fail", "nodes": []}')

    assert captured["ms"] == 30000
    assert bridge._obs_tree_retry_remaining == 1


def test_bridge_obs_append_command_emits_success():
    _ensure_qt_app()

    class DummyResult:
        def __init__(self, ok=True, message="ok", path="C:/Vault/test.md"):
            self.ok = ok
            self.message = message
            self.path = path

    bridge = WebBridge()
    bridge.llm_client = object()

    class DummyObsManager:
        def append_file(self, rel_path, content, create_if_missing=True):
            return DummyResult(ok=True, message="ok", path=f"C:/Vault/{rel_path}")

        def get_tree_lines(self, max_lines=120):
            return []

        def get_checked_file_contents(self, **kwargs):
            return []

    bridge.obsidian_manager = DummyObsManager()

    received = []
    bridge.message_received.connect(lambda text, emotion: received.append((text, emotion)))

    handled = bridge._handle_obs_command("/obs append test.md :: 추가 텍스트")
    assert handled is True
    assert received
    assert "추가 완료" in received[-1][0]


def test_bridge_obs_summarize_command_starts_ai_worker(monkeypatch):
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.llm_client = object()

    class DummyObsManager:
        def read_file(self, rel_path):
            return "# 제목\n내용"

        def get_tree_lines(self, max_lines=120):
            return ["[FILE] test.md"]

        def get_checked_file_contents(self, **kwargs):
            return [("test.md", "체크 파일 내용")]

    bridge.obsidian_manager = DummyObsManager()

    captured = {}

    def fake_start(message_with_time: str, images_data=None):
        captured["message_with_time"] = message_with_time

    monkeypatch.setattr(bridge, "_start_ai_worker", fake_start)
    handled = bridge._handle_obs_command("/obs summarize test.md")
    assert handled is True
    assert "[Obsidian 트리 구조]" in captured["message_with_time"]
    assert "[Obsidian 체크된 파일 본문]" in captured["message_with_time"]
    assert "[요약 대상 파일: test.md]" in captured["message_with_time"]


def test_bridge_note_command_activates_obsidian_lazy_connection(monkeypatch):
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.llm_client = object()

    captured = {"activated": 0, "started": 0}

    monkeypatch.setattr(
        bridge,
        "_activate_obsidian_integration",
        lambda: captured.__setitem__("activated", captured["activated"] + 1),
        raising=False,
    )
    monkeypatch.setattr(
        bridge,
        "_start_note_worker",
        lambda note_request, message_with_time, note_recent_context="": captured.__setitem__("started", captured["started"] + 1),
    )

    handled = bridge._handle_note_command("/note 자기소개서 수정해줘")

    assert handled is True
    assert captured["activated"] == 1

    assert captured["started"] == 1


def test_bridge_obs_command_activates_obsidian_lazy_connection(monkeypatch):
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.llm_client = object()

    class DummyObsManager:
        def read_file(self, rel_path):
            return "# 제목\n내용"

        def get_tree_lines(self, max_lines=120):
            return []

        def get_checked_file_contents(self, **kwargs):
            return []

    bridge.obsidian_manager = DummyObsManager()

    captured = {"activated": 0}

    monkeypatch.setattr(
        bridge,
        "_activate_obsidian_integration",
        lambda: captured.__setitem__("activated", captured["activated"] + 1),
        raising=False,
    )
    monkeypatch.setattr(bridge, "_start_ai_worker", lambda message_with_time, images_data=None: None)

    handled = bridge._handle_obs_command("/obs summarize test.md")

    assert handled is True
    assert captured["activated"] == 1


def test_bridge_obs_summarize_command_uses_configured_checked_file_limits(monkeypatch):
    _ensure_qt_app()

    class DummySettings:
        def get(self, key, default=None):
            values = {
                "obsidian_checked_max_chars_per_file": 9000,
                "obsidian_checked_total_max_chars": 18000,
            }
            return values.get(key, default)

    bridge = WebBridge()
    bridge.llm_client = object()
    bridge.settings = DummySettings()

    captured = {}

    class DummyObsManager:
        def read_file(self, rel_path):
            return "# 제목\n내용"

        def get_tree_lines(self, max_lines=120):
            return []

        def get_checked_file_contents(self, **kwargs):
            captured["kwargs"] = dict(kwargs)
            return []

    bridge.obsidian_manager = DummyObsManager()

    monkeypatch.setattr(bridge, "_start_ai_worker", lambda message_with_time, images_data=None: None)

    handled = bridge._handle_obs_command("/obs summarize test.md")

    assert handled is True
    assert captured["kwargs"]["max_chars_per_file"] == 9000
    assert captured["kwargs"]["total_max_chars"] == 18000


def test_aiworker_diary_flow_uses_one_shot_and_does_not_need_history(tmp_path: Path):
    _ensure_qt_app()

    class DummyLLM:
        async def generate_markdown_document(self, message: str) -> str:
            return "# 문서\n\n내용"

        async def generate_diary_completion_reply(self, context_message: str):
            assert "성공적으로 파일 작성에 완료되었습니다." in context_message
            assert "[작성된 md 파일 본문]" in context_message
            assert "[저장 결과]" in context_message
            assert "- 대상:" in context_message
            assert "- 경로:" in context_message
            return "성공적으로 파일 작성에 완료되었습니다. 완료됐어요.", "smile", "", []

    from src.core.bridge import AIWorker

    service = DiaryService(tmp_path / "diary")
    worker = AIWorker(
        llm_client=DummyLLM(),
        message="[현재 시각: 2026-02-28 20:00]\n오늘 있었던 일을 일기로 써줘",
        diary_request="오늘 있었던 일을 일기로 써줘",
        diary_service=service,
    )

    result = asyncio.run(worker._run_diary_flow())
    assert result[0].startswith("성공적으로 파일 작성에 완료되었습니다.")
    saved_files = list((tmp_path / "diary").glob("*.md"))
    assert len(saved_files) == 1


def test_aiworker_note_flow_fallbacks_when_plan_write_content_is_empty():
    _ensure_qt_app()

    class DummyLLM:
        async def generate_note_command_plan(self, context_message: str) -> str:
            return """
# NOTE PLAN
- summary: 빈 본문 계획
- stop_on_error: true
## COMMANDS
1. obsidian write "ene_01.md" ""
"""

        async def generate_markdown_document(self, message: str) -> str:
            return "# 에네의 자기소개\n\n안녕하세요, 에네입니다."

        async def generate_note_execution_report(self, context_message: str):
            assert "content-write-fallback" in context_message
            return "완료 보고", "normal", "", []

    class DummyCompleted:
        def __init__(self):
            self.returncode = 0
            self.stdout = "ok"
            self.stderr = ""

    class DummyObsManager:
        def __init__(self):
            self.calls = []

        def get_tree_lines(self, max_lines=120, allow_retry=True):
            return ["[FILE] ene_01.md"]

        def get_checked_file_contents(self, **kwargs):
            return []

        def execute_cli_args(self, args):
            self.calls.append(list(args))
            return DummyCompleted()

    from src.ai.note_service import NoteService
    from src.core.bridge import AIWorker

    manager = DummyObsManager()
    worker = AIWorker(
        llm_client=DummyLLM(),
        message="[현재 시각: 2026-03-06 10:00]\n에네 자기소개 작성",
        note_request="에네의 자기소개를 ene_01.md라는 제목으로 작성해줘",
        note_service=NoteService(),
        obsidian_manager=manager,
    )

    result = asyncio.run(worker._run_note_flow())
    assert result[0] == "완료 보고"
    assert len(manager.calls) == 1
    assert manager.calls[0][0] == "create"
    assert manager.calls[0][1] == "path=ene_01.md"
    assert manager.calls[0][2].startswith("content=# 에네의 자기소개")
    assert "overwrite" in manager.calls[0]


def test_aiworker_note_flow_uses_plan_path_when_request_has_no_md_path():
    _ensure_qt_app()

    class DummyLLM:
        async def generate_note_command_plan(self, context_message: str) -> str:
            return """
# NOTE PLAN
- summary: 경로는 계획에서 제공
- stop_on_error: true
## COMMANDS
1. obsidian create "notes/ene_auto.md"
"""

        async def generate_markdown_document(self, message: str) -> str:
            return "# 자동 생성\n\n본문"

        async def generate_note_execution_report(self, context_message: str):
            assert "notes/ene_auto.md" in context_message
            return "완료 보고", "normal", "", []

    class DummyCompleted:
        def __init__(self):
            self.returncode = 0
            self.stdout = "ok"
            self.stderr = ""

    class DummyObsManager:
        def __init__(self):
            self.calls = []

        def get_tree_lines(self, max_lines=120, allow_retry=True):
            return []

        def get_checked_file_contents(self, **kwargs):
            return []

        def execute_cli_args(self, args):
            self.calls.append(list(args))
            return DummyCompleted()

    from src.ai.note_service import NoteService
    from src.core.bridge import AIWorker

    manager = DummyObsManager()
    worker = AIWorker(
        llm_client=DummyLLM(),
        message="[현재 시각: 2026-03-06 10:00]\n에네 자기소개 작성",
        note_request="에네의 자기소개를 작성해줘",
        note_service=NoteService(),
        obsidian_manager=manager,
    )

    result = asyncio.run(worker._run_note_flow())
    assert result[0] == "완료 보고"
    assert len(manager.calls) == 2
    assert manager.calls[0][0] == "create"
    assert manager.calls[0][1] == "path=notes/ene_auto.md"
    assert manager.calls[1][0] == "create"
    assert manager.calls[1][1] == "path=notes/ene_auto.md"
    assert manager.calls[1][2].startswith("content=# 자동 생성")
    assert "overwrite" in manager.calls[1]


def test_aiworker_note_flow_generates_path_when_request_has_no_md_and_plan_has_no_path():
    _ensure_qt_app()

    class DummyLLM:
        async def generate_note_command_plan(self, context_message: str) -> str:
            return """
# NOTE PLAN
- summary: 데일리 기록 시도
- stop_on_error: true
## COMMANDS
1. obsidian daily:append content="오늘 있었던 일을 기록"
"""

        async def generate_markdown_document(self, message: str) -> str:
            return "# 오늘의 일기\n\n본문"

        async def generate_note_execution_report(self, context_message: str):
            assert "content-write-fallback" in context_message
            return "완료 보고", "normal", "", []

    class FailedCompleted:
        def __init__(self):
            self.returncode = -1
            self.stdout = ""
            self.stderr = ""

    class OkCompleted:
        def __init__(self):
            self.returncode = 0
            self.stdout = "ok"
            self.stderr = ""

    class DummyObsManager:
        def __init__(self):
            self.calls = []

        def get_tree_lines(self, max_lines=120, allow_retry=True):
            return []

        def get_checked_file_contents(self, **kwargs):
            return []

        def execute_cli_args(self, args):
            self.calls.append(list(args))
            if len(self.calls) == 1:
                return FailedCompleted()
            return OkCompleted()

    from src.ai.note_service import NoteService
    from src.core.bridge import AIWorker

    manager = DummyObsManager()
    worker = AIWorker(
        llm_client=DummyLLM(),
        message="[현재 시각: 2026-03-11 02:10]\n오늘의 일기를 작성해줘",
        note_request="오늘의 일기를 작성해줘",
        note_service=NoteService(),
        obsidian_manager=manager,
    )

    result = asyncio.run(worker._run_note_flow())
    assert result[0] == "완료 보고"
    assert len(manager.calls) == 2
    assert manager.calls[0][0] == "daily:append"
    assert manager.calls[1][0] == "create"
    assert manager.calls[1][1].endswith(".md")
    assert manager.calls[1][2].startswith("content=# 오늘의 일기")
    assert "overwrite" in manager.calls[1]

def test_bridge_tts_error_restores_pending_response():
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.pending_response = ("복구할 응답", "normal")
    bridge._is_rerolling = True

    received = []
    reroll_states = []
    bridge.message_received.connect(lambda text, emotion: received.append((text, emotion)))
    bridge.reroll_state_changed.connect(lambda state: reroll_states.append(bool(state)))

    bridge._on_tts_error("mock error")

    assert received == [("복구할 응답", "normal")]
    assert bridge.pending_response is None
    assert bridge._is_rerolling is False
    assert reroll_states and reroll_states[-1] is False


def test_bridge_edit_without_payload_resets_pending_ui_state():
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.llm_client = object()

    reroll_states = []
    notices = []
    bridge.reroll_state_changed.connect(lambda state: reroll_states.append(bool(state)))
    bridge.summary_notice.connect(lambda message, level: notices.append((message, level)))

    bridge.edit_last_user_message("수정 메시지")

    assert reroll_states and reroll_states[-1] is False
    assert notices
    assert "/diary 응답은 Edit로 다시 생성할 수 없어요." in notices[-1][0]
    assert notices[-1][1] == "info"


def test_bridge_reroll_without_payload_resets_pending_ui_state():
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.llm_client = object()

    reroll_states = []
    notices = []
    bridge.reroll_state_changed.connect(lambda state: reroll_states.append(bool(state)))
    bridge.summary_notice.connect(lambda message, level: notices.append((message, level)))

    bridge.reroll_last_response()

    assert reroll_states and reroll_states[-1] is False
    assert notices
    assert notices[-1][1] == "info"
